"""Detecção de buracos na série.

Um gap silencioso é pior que um erro: a janela da regressão passa a cobrir um período
maior do que ela pensa que cobre, o ATR subestima a volatilidade real, e o backtest
reporta uma borda que não existe. Rodar `dands doctor` antes de confiar no dado.

Cripto é 24/7 → a grade esperada é exata e todo buraco é um gap de verdade.
Ação tem feriado e pregão suspenso → sem calendário oficial, tratamos dias úteis
ausentes como CANDIDATOS a gap (a maioria será feriado). Por isso o relatório
distingue os dois casos em vez de fingir uma precisão que não temos.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from app.core.config import Asset, Market, Timeframe
from app.ingest import store

_FREQ = {Timeframe.M15: "15min", Timeframe.D1: "1D"}


@dataclass
class GapReport:
    asset: Asset
    tf: Timeframe
    n_velas: int
    inicio: pd.Timestamp | None
    fim: pd.Timestamp | None
    faltando: list[pd.Timestamp]
    exato: bool  # True = grade determinística (cripto); False = candidatos (ação)

    @property
    def ok(self) -> bool:
        return self.n_velas > 0 and not self.faltando

    @property
    def cobertura_pct(self) -> float:
        esperado = self.n_velas + len(self.faltando)
        return 100.0 * self.n_velas / esperado if esperado else 0.0


def detect(asset: Asset, tf: Timeframe) -> GapReport:
    df = store.read(asset, tf)
    if df.empty:
        return GapReport(asset, tf, 0, None, None, [], asset.market is Market.CRYPTO)

    ts = df["timestamp"]
    inicio, fim = ts.iloc[0], ts.iloc[-1]
    exato = asset.market is Market.CRYPTO

    if exato:
        esperado = pd.date_range(inicio, fim, freq=_FREQ[tf], tz="UTC")
    else:
        # Sem calendário de feriados: dias úteis como aproximação superior.
        esperado = pd.bdate_range(inicio.normalize(), fim.normalize(), tz="UTC")

    presente = set(ts) if exato else {t.normalize() for t in ts}
    faltando = [t for t in esperado if t not in presente]

    return GapReport(asset, tf, len(df), inicio, fim, faltando, exato)
