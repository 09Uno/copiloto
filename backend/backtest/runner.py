"""Orquestra o backtest e faz a divisão que decide tudo: dentro × FORA da amostra.

Um resultado bom dentro da amostra não significa nada — com parâmetros suficientes dá para
ajustar qualquer curva ao passado. O que vale é o desempenho **fora da amostra**: no pedaço do
histórico que o calibrador nunca viu.

Corte temporal, nunca aleatório. Embaralhar série temporal (k-fold) treina no futuro e testa no
passado — o erro que faz backtest de ML parecer genial e quebrar no primeiro dia real.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from app.core.config import Market, Params, Timeframe, watchlist
from app.ingest import store
from backtest import core, metrics
from backtest.metrics import Metricas

FRACAO_IN_SAMPLE = 0.70  # 70% do histórico calibra; os últimos 30% julgam


def cache_xsect(p: Params) -> core.CacheXSect:
    """Pré-computa o que não depende dos parâmetros do grid. Reutilizado nas 81 combinações."""
    from app.core import b3_universe

    painel, _ = b3_universe.load()
    return core.CacheXSect(painel, p, pd.Timestamp("2010-01-01", tz="UTC"))


@dataclass
class Resultado:
    estrategia: str
    mercado: str
    timeframe: str
    dentro: Metricas | None
    fora: Metricas | None
    trades: pd.DataFrame

    @property
    def veredito(self) -> str:
        """O portão da Fase 2. Só o FORA da amostra tem voto."""
        if self.fora is None or self.fora.n < 30:
            return "SEM AMOSTRA"
        return "TEM BORDA" if self.fora.tem_borda else "SEM BORDA"


def _corte(trades: pd.DataFrame) -> pd.Timestamp:
    return trades["entrada_em"].quantile(FRACAO_IN_SAMPLE)


def _split(trades: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    if trades.empty:
        return trades, trades
    c = _corte(trades)
    return trades[trades["entrada_em"] <= c], trades[trades["entrada_em"] > c]


def mean_rev(p: Params, market: Market, tf: Timeframe) -> Resultado:
    todos: list[core.Trade] = []
    bh, n_bh = 0.0, 0

    for a in watchlist(market):
        if tf not in a.timeframes:
            continue
        df = store.read(a, tf)
        if len(df) < p.min_velas + 50:
            continue
        todos.extend(core.run_mean_rev(df, p, market, tf, a.ticker))
        bh += metrics.buy_and_hold(df)
        n_bh += 1

    t = core.to_frame(todos)
    dentro, fora = _split(t)
    bh_medio = bh / n_bh if n_bh else None

    return Resultado(
        estrategia="MEAN_REV",
        mercado=market.value,
        timeframe=tf.value,
        dentro=metrics.compute(dentro, buy_hold_pct=bh_medio),
        fora=metrics.compute(fora, buy_hold_pct=bh_medio),
        trades=t,
    )


def cross_sectional(
    p: Params, market: Market, tf: Timeframe, cache: core.CacheXSect | None = None
) -> Resultado:
    from app.core import b3_universe

    painel, comp = b3_universe.load()
    inicio = pd.Timestamp("2010-01-01", tz="UTC")

    t = core.to_frame(
        core.run_cross_sectional(painel, comp, p, market, tf, inicio, cache=cache)
    )
    dentro, fora = _split(t)

    return Resultado(
        estrategia="XSECT",
        mercado=market.value,
        timeframe=tf.value,
        dentro=metrics.compute(dentro),
        fora=metrics.compute(fora),
        trades=t,
    )
