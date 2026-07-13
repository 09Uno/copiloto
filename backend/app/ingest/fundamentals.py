"""Fundamentos (balanço e indicadores) via yfinance.

Aqui o Yahoo é aceitável — e não por preguiça. Fundamento muda **uma vez por trimestre**;
um erro de dado se detecta olhando (P/L negativo, patrimônio zerado), e a decisão de carregar
uma ação por anos não morre por causa de um dia de dado ruim. É o oposto do preço intradiário.

O que NÃO dá para fazer com esta fonte: backtest fundamentalista honesto. O yfinance entrega
o balanço de HOJE, não o que estava publicado em 2015 — e ele revisa números retroativamente.
Um backtest sobre isso teria lookahead embutido. Por isso o módulo VALUE avalia o presente e
**não entra na esteira de rótulos do ML** (SPEC §8.4) enquanto não houver histórico
point-in-time de balanços.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass

import yfinance as yf

from app.core.config import Asset


@dataclass(frozen=True)
class Fundamentos:
    ticker: str
    preco: float | None = None
    lpa: float | None = None            # lucro por ação (EPS, 12 meses)
    vpa: float | None = None            # valor patrimonial por ação
    dividendo_yield: float | None = None
    payout: float | None = None
    roe: float | None = None
    divida_liquida_ebitda: float | None = None
    pl: float | None = None             # preço / lucro
    pvp: float | None = None            # preço / valor patrimonial
    ev_ebitda: float | None = None
    setor: str | None = None

    @property
    def completo(self) -> bool:
        """Sem LPA e VPA não há avaliação clássica — nem Graham, nem P/L, nem P/VP."""
        return self.preco is not None and self.lpa is not None and self.vpa is not None


def _num(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f else f  # NaN


def fetch(asset: Asset) -> Fundamentos:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            info = yf.Ticker(asset.ticker).info or {}
        except Exception:  # noqa: BLE001 — fonte instável; ausência de fundamento é normal
            return Fundamentos(ticker=asset.ticker)

    preco = _num(info.get("currentPrice")) or _num(info.get("regularMarketPrice"))
    lpa = _num(info.get("trailingEps"))
    vpa = _num(info.get("bookValue"))

    return Fundamentos(
        ticker=asset.ticker,
        preco=preco,
        lpa=lpa,
        vpa=vpa,
        dividendo_yield=_num(info.get("dividendYield")),
        payout=_num(info.get("payoutRatio")),
        roe=_num(info.get("returnOnEquity")),
        divida_liquida_ebitda=_num(info.get("debtToEquity")),
        pl=_num(info.get("trailingPE")),
        pvp=_num(info.get("priceToBook")),
        ev_ebitda=_num(info.get("enterpriseToEbitda")),
        setor=info.get("sector"),
    )
