"""Configuração do motor: hiperparâmetros (params.yaml) e universo de ativos.

Os hiperparâmetros são carregados como um objeto imutável e validado. O motor nunca
lê `params.yaml` direto — ele recebe `Params` por injeção, para que o backtest possa
varrer o grid (Fase 2) sem tocar em arquivo.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel

from app.core import universe

BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_DIR = BACKEND_DIR.parent
DATA_DIR = PROJECT_DIR / "data"
PARAMS_PATH = Path(__file__).with_name("params.yaml")


class Market(StrEnum):
    CRYPTO = "CRYPTO"
    B3 = "B3"
    US = "US"


class Timeframe(StrEnum):
    M15 = "15m"
    D1 = "1d"


# ---------------------------------------------------------------- hiperparâmetros


class Regressao(BaseModel):
    janela: int
    base: str


class Bandas(BaseModel):
    janela_media: int
    n_sigma_entrada: float


class Regime(BaseModel):
    r2_max_lateral: float
    nervoso_atr_mult: float
    nervoso_atr_janela: int


class Score(BaseModel):
    peso_desvio: float
    peso_volume: float
    peso_rr: float
    peso_regime: float

    @property
    def total(self) -> float:
        return self.peso_desvio + self.peso_volume + self.peso_rr + self.peso_regime


class Volume(BaseModel):
    janela_zscore: int
    z_minimo: float
    base: str


class Risco(BaseModel):
    atr_janela: int
    stop_atr_mult: float
    rr_minimo: float
    horizonte_max: dict[str, int]


class CrossSectional(BaseModel):
    janela_reversao: int
    n_extremos: int
    min_universo: int


class Momentum(BaseModel):
    janela_formacao: int
    gap: int
    n_extremos: int
    holding: int
    stop_atr_mult: float
    min_universo: int
    long_only: bool = True


class Custos(BaseModel):
    cripto_taker_pct: float
    acoes_br_pct: float
    acoes_us_pct: float
    slippage_pct: float

    def por_perna(self, market: Market) -> float:
        """Custo percentual de UMA perna (entrada ou saída), já com slippage."""
        taxa = {
            Market.CRYPTO: self.cripto_taker_pct,
            Market.B3: self.acoes_br_pct,
            Market.US: self.acoes_us_pct,
        }[market]
        return taxa + self.slippage_pct

    def ida_e_volta(self, market: Market) -> float:
        """Custo total de um trade completo. É isto que sai da expectância."""
        return 2 * self.por_perna(market)


class Params(BaseModel, frozen=True):
    engine_version: str
    regressao: Regressao
    bandas: Bandas
    regime: Regime
    score: Score
    volume: Volume
    risco: Risco
    custos: Custos
    cross_sectional: CrossSectional
    momentum: Momentum

    @property
    def min_velas(self) -> int:
        """Velas necessárias antes que TODAS as features existam.

        Emitir sinal antes disso significa calcular indicador sobre janela incompleta —
        um dos jeitos mais silenciosos de contaminar o backtest.
        """
        return max(
            self.regressao.janela,
            self.bandas.janela_media,
            self.volume.janela_zscore,
            self.regime.nervoso_atr_janela,
            self.risco.atr_janela + 1,
        )


def _merge(base: dict, over: dict) -> dict:
    """Merge profundo: o perfil sobrescreve só o que declara."""
    out = dict(base)
    for k, v in over.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


@lru_cache
def load_params(
    market: Market | None = None,
    timeframe: Timeframe | None = None,
    path: Path | None = None,
) -> Params:
    """Parâmetros do PERFIL (mercado × timeframe), com fallback para o `default`.

    Não existe um parâmetro único que sirva para uma vela de 15 minutos do BTC e para um
    pregão da VALE3 — são processos estatísticos diferentes. Cada perfil é calibrado
    independentemente na Fase 2; o `default` é só o ponto de partida.
    """
    raw = yaml.safe_load((path or PARAMS_PATH).read_text(encoding="utf-8"))
    cfg = raw["default"] | {"engine_version": raw["engine_version"]}

    if market and timeframe:
        chave = f"{market.value}:{timeframe.value}"
        if over := raw.get("perfis", {}).get(chave):
            cfg = _merge(cfg, over)

    return Params.model_validate(cfg)


# ---------------------------------------------------------------- universo de ativos


class Asset(BaseModel, frozen=True):
    ticker: str
    market: Market
    name: str
    timeframes: tuple[Timeframe, ...]

    @property
    def slug(self) -> str:
        """Nome seguro para caminho de arquivo (PETR4.SA → PETR4_SA)."""
        return self.ticker.replace(".", "_").replace("/", "_")

    @property
    def currency(self) -> str:
        """Moeda da banca em que este ativo é operado (SPEC §8.1).

        USDT é tratado como USD: os pares da watchlist são todos */USDT.
        """
        return "BRL" if self.market is Market.B3 else "USD"

    def params(self) -> Params:
        """Atalho: os parâmetros do perfil deste ativo, por timeframe."""
        return load_params(self.market, self.timeframes[0])


def _build_watchlist() -> tuple[Asset, ...]:
    """Universo gerado a partir de `universe.py`.

    Day trade (15m) só existe onde há dado em tempo real: cripto. Ação com delay de 15 minutos
    não sustenta reversão intradiária (SPEC §1) — por isso ela só tem `1d`.
    """
    ativos: list[Asset] = []

    for t in universe.CRYPTO_TICKERS:
        ativos.append(
            Asset(ticker=t, market=Market.CRYPTO, name=t.removesuffix("USDT"),
                  timeframes=(Timeframe.M15, Timeframe.D1))
        )
    for t in universe.B3_TICKERS:
        ativos.append(
            Asset(ticker=f"{t}.SA", market=Market.B3, name=t, timeframes=(Timeframe.D1,))
        )
    for t in universe.US_TICKERS:
        ativos.append(Asset(ticker=t, market=Market.US, name=t, timeframes=(Timeframe.D1,)))

    return tuple(ativos)


WATCHLIST: tuple[Asset, ...] = _build_watchlist()


def watchlist(market: Market | None = None) -> list[Asset]:
    return [a for a in WATCHLIST if market is None or a.market == market]
