"""Motor do backtest (Fase 2) — o portão de decisão do projeto.

Importa `app.engine` e roda **exatamente o mesmo código** da produção. Se fossem duas
implementações, divergiriam e o backtest viraria ficção.

As três defesas contra o auto-engano, que são o motivo de este arquivo existir:

1. **A entrada é na ABERTURA do pregão seguinte.** Você não consegue comprar no fechamento que
   acabou de observar — o sinal só existe *porque* a vela fechou. Assumir entrada no próprio
   close é a forma mais comum e mais silenciosa de inflar backtest.

2. **O R:R é recalculado no preço de entrada real.** Se a abertura veio pior que o gatilho, a
   operação ficou pior do que a que o motor aprovou — e é descartada, exatamente como a
   produção faria (SPEC §8.3). O alvo e o stop NÃO se movem: são níveis do mercado.

3. **Custos em tudo.** Uma estratégia lucrativa só antes de custos é uma estratégia que perde
   dinheiro.

O resultado de cada trade é medido em **múltiplos de R** (R = o risco assumido). Um trade que
bate o alvo a 2R devolve 2× o que arriscou. É o que torna comparáveis um trade de BTC e um de
ITUB4, e o que liga o resultado ao sizing do SPEC §8.2.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from app.core.config import Market, Params, Timeframe
from app.engine import barriers, indicators, regime, signals
from app.engine.signals import AlertType


@dataclass
class Trade:
    ticker: str
    strategy: str
    side: str
    entrada_em: pd.Timestamp
    saida_em: pd.Timestamp
    entrada: float
    saida: float
    stop: float
    alvo: float
    outcome: str
    retorno_liquido_pct: float
    r_multiple: float          # o que importa: quantos "riscos" o trade devolveu
    velas: int
    score: int


def _r_multiple(entrada: float, stop: float, retorno_liquido_pct: float) -> float:
    risco_pct = abs(entrada - stop) / entrada * 100.0
    return retorno_liquido_pct / risco_pct if risco_pct > 0 else 0.0


def run_mean_rev(
    df: pd.DataFrame,
    p: Params,
    market: Market,
    tf: Timeframe,
    ticker: str,
) -> list[Trade]:
    """Reversão absoluta (SPEC §3), papel a papel."""
    f = indicators.compute(df, p)
    f["market_regime"] = regime.classify(f, p)
    sinais = signals.generate(f, p, market)
    if sinais.empty:
        return []

    horizonte = p.risco.horizonte_max[tf.value]
    custo = p.custos.ida_e_volta(market)
    ohlc = f.reset_index(drop=True)
    pos = {t: i for i, t in enumerate(ohlc["timestamp"])}

    trades: list[Trade] = []
    livre_a_partir_de = -1  # uma posição por vez, por papel

    for ts, s in sinais.iterrows():
        i = pos.get(f.loc[ts, "timestamp"]) if ts in f.index else None
        if i is None or i <= livre_a_partir_de or i + 1 >= len(ohlc):
            continue

        # --- Entrada na ABERTURA da vela seguinte. Nunca no close que gerou o sinal.
        entrada = float(ohlc["open"].iloc[i + 1])
        if entrada <= 0:
            continue

        side = AlertType(s["alert_type"])
        alvo, stop = float(s["take_profit_price"]), float(s["stop_loss_price"])

        # --- O gap de abertura pode ter invalidado a operação: já passou do stop ou do alvo.
        sinal = 1.0 if side is AlertType.BUY else -1.0
        if sinal * (entrada - stop) <= 0 or sinal * (alvo - entrada) <= 0:
            continue

        # --- R:R recalculado no preço REAL. Alvo e stop são níveis do mercado e não se
        # movem porque a abertura veio pior — o que piora é o nosso risco:retorno.
        rr = abs(alvo - entrada) / abs(entrada - stop)
        if rr < p.risco.rr_minimo:
            continue

        r = barriers.evaluate(
            ohlc, entry_pos=i, side=side, trigger=entrada,
            take_profit=alvo, stop_loss=stop,
            horizonte=horizonte, custo_ida_volta_pct=custo,
        )
        if r is None:
            continue

        trades.append(
            Trade(
                ticker=ticker, strategy="MEAN_REV", side=side.value,
                entrada_em=ohlc["timestamp"].iloc[i + 1],
                saida_em=ohlc["timestamp"].iloc[r.exit_index],
                entrada=entrada, saida=r.exit_price, stop=stop, alvo=alvo,
                outcome=r.outcome.value,
                retorno_liquido_pct=r.retorno_liquido_pct,
                r_multiple=_r_multiple(entrada, stop, r.retorno_liquido_pct),
                velas=r.velas_ate_saida, score=int(s["calculated_score"]),
            )
        )
        livre_a_partir_de = r.exit_index

    return trades


class CacheXSect:
    """Tudo que NÃO depende dos parâmetros do grid, computado uma única vez.

    O grid varia stop, R:R, janela de reversão e nº de extremos — e **nenhum deles muda os
    indicadores**. Recalcular ATR e regressão dos 373 papéis a cada uma das 81 combinações é
    puro desperdício: era o que fazia o grid levar mais de uma hora.
    """

    def __init__(self, painel: pd.DataFrame, p: Params, inicio: pd.Timestamp) -> None:
        self.por_ticker: dict[str, pd.DataFrame] = {}
        self.pos: dict[str, dict] = {}
        for tk, g in painel.groupby("ticker"):
            g = g.sort_values("timestamp").reset_index(drop=True)
            f = indicators.compute(g, p)
            self.por_ticker[tk] = f
            self.pos[tk] = {t: i for i, t in enumerate(f["timestamp"])}

        datas = sorted(d for d in painel["timestamp"].unique() if d >= inicio)
        self.rebal = [d for d in datas if pd.Timestamp(d).dayofweek == 4]  # sextas
        self.rankings: dict[tuple, pd.DataFrame] = {}  # (janela, data) → ranking


def run_cross_sectional(
    painel: pd.DataFrame,
    composicao: pd.DataFrame,
    p: Params,
    market: Market,
    tf: Timeframe,
    inicio: pd.Timestamp,
    cache: CacheXSect | None = None,
) -> list[Trade]:
    """Reversão cross-sectional (SPEC §11), sobre o universo POINT-IN-TIME."""
    from app.core import b3_universe
    from app.engine import cross_sectional

    horizonte = p.risco.horizonte_max[tf.value]
    custo = p.custos.ida_e_volta(market)

    cache = cache or CacheXSect(painel, p, inicio)
    por_ticker = cache.por_ticker

    trades: list[Trade] = []
    for d in cache.rebal:
        membros = b3_universe.membros_em(composicao, d)
        if len(membros) < p.cross_sectional.min_universo:
            continue

        # O ranking só depende da janela de reversão — reaproveitável entre combinações.
        chave = (p.cross_sectional.janela_reversao, d)
        if chave not in cache.rankings:
            cache.rankings[chave] = cross_sectional.rank_universo(painel, d, membros, p)
        rank = cache.rankings[chave]
        if rank.empty:
            continue

        atrs = {}
        for tk in rank["ticker"]:
            f = por_ticker.get(tk)
            i = cache.pos.get(tk, {}).get(d) if f is not None else None
            if i is None:
                continue
            a = f["atr"].iloc[i]
            if pd.notna(a) and a > 0:
                atrs[tk] = float(a)

        sinais = cross_sectional.generate(rank, atrs, d, p, custo)

        for _, s in sinais.iterrows():
            f = por_ticker[s["ticker"]]
            i = cache.pos[s["ticker"]].get(d)
            if i is None or i + 1 >= len(f):
                continue

            entrada = float(f["open"].iloc[i + 1])
            if entrada <= 0:
                continue

            side = AlertType(s["alert_type"])
            alvo, stop = float(s["take_profit_price"]), float(s["stop_loss_price"])
            sinal = 1.0 if side is AlertType.BUY else -1.0
            if sinal * (entrada - stop) <= 0 or sinal * (alvo - entrada) <= 0:
                continue
            if abs(alvo - entrada) / abs(entrada - stop) < p.risco.rr_minimo:
                continue

            r = barriers.evaluate(
                f, entry_pos=i, side=side, trigger=entrada,
                take_profit=alvo, stop_loss=stop,
                horizonte=horizonte, custo_ida_volta_pct=custo,
            )
            if r is None:
                continue

            trades.append(
                Trade(
                    ticker=s["ticker"], strategy="XSECT", side=side.value,
                    entrada_em=f["timestamp"].iloc[i + 1],
                    saida_em=f["timestamp"].iloc[r.exit_index],
                    entrada=entrada, saida=r.exit_price, stop=stop, alvo=alvo,
                    outcome=r.outcome.value,
                    retorno_liquido_pct=r.retorno_liquido_pct,
                    r_multiple=_r_multiple(entrada, stop, r.retorno_liquido_pct),
                    velas=r.velas_ate_saida, score=int(s["calculated_score"]),
                )
            )

    return trades


def to_frame(trades: list[Trade]) -> pd.DataFrame:
    if not trades:
        return pd.DataFrame(
            columns=[
                "ticker", "strategy", "side", "entrada_em", "saida_em", "entrada", "saida",
                "stop", "alvo", "outcome", "retorno_liquido_pct", "r_multiple", "velas", "score",
            ]
        )
    return pd.DataFrame([t.__dict__ for t in trades]).sort_values("entrada_em").reset_index(
        drop=True
    )
