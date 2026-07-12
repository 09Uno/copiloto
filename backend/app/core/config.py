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
from pydantic import BaseModel, Field

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


class Volume(BaseModel):
    janela_zscore: int
    z_minimo: float
    base: str


class Risco(BaseModel):
    atr_janela: int
    stop_atr_mult: float
    rr_minimo: float
    horizonte_max: dict[str, int]


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
    volume: Volume
    risco: Risco
    custos: Custos

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
            self.risco.atr_janela + 1,
        )


@lru_cache
def load_params(path: Path | None = None) -> Params:
    raw = yaml.safe_load((path or PARAMS_PATH).read_text(encoding="utf-8"))
    return Params.model_validate(raw)


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


# Day trade (15m) só existe onde há dado em tempo real: cripto.
# Ação com delay de 15min não faz reversão intradiária — ver SPEC.md §1.
WATCHLIST: tuple[Asset, ...] = (
    # --- Cripto (Binance): único mercado com 15m viável
    Asset(ticker="BTCUSDT", market=Market.CRYPTO, name="Bitcoin",
          timeframes=(Timeframe.M15, Timeframe.D1)),
    Asset(ticker="ETHUSDT", market=Market.CRYPTO, name="Ethereum",
          timeframes=(Timeframe.M15, Timeframe.D1)),
    Asset(ticker="SOLUSDT", market=Market.CRYPTO, name="Solana",
          timeframes=(Timeframe.M15, Timeframe.D1)),
    # --- B3 (EOD apenas)
    Asset(ticker="PETR4.SA", market=Market.B3, name="Petrobras PN",
          timeframes=(Timeframe.D1,)),
    Asset(ticker="VALE3.SA", market=Market.B3, name="Vale ON",
          timeframes=(Timeframe.D1,)),
    Asset(ticker="ITUB4.SA", market=Market.B3, name="Itaú Unibanco PN",
          timeframes=(Timeframe.D1,)),
    Asset(ticker="BBAS3.SA", market=Market.B3, name="Banco do Brasil ON",
          timeframes=(Timeframe.D1,)),
    # --- EUA (EOD apenas)
    Asset(ticker="AAPL", market=Market.US, name="Apple", timeframes=(Timeframe.D1,)),
    Asset(ticker="MSFT", market=Market.US, name="Microsoft", timeframes=(Timeframe.D1,)),
    Asset(ticker="NVDA", market=Market.US, name="NVIDIA", timeframes=(Timeframe.D1,)),
)


def watchlist(market: Market | None = None) -> list[Asset]:
    return [a for a in WATCHLIST if market is None or a.market == market]
