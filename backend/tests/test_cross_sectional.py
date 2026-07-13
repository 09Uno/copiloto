"""Reversão cross-sectional.

O teste central é `test_neutraliza_o_mercado`: sem subtrair a mediana do universo, num crash
geral a estratégia compraria tudo — estaria comprando o índice, não a distorção, e o "sinal"
seria beta disfarçado de alfa.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.core.config import Market, Timeframe, load_params
from app.engine import cross_sectional
from app.engine.signals import AlertType

P = load_params(Market.B3, Timeframe.D1)
DATA = pd.Timestamp("2024-03-01", tz="UTC")


def _painel(retornos_por_ticker: dict[str, float], n: int = 30) -> pd.DataFrame:
    """Painel onde cada ticker acumula exatamente `retorno` nos últimos 5 pregões."""
    linhas = []
    datas = pd.date_range(end=DATA, periods=n, freq="1D", tz="UTC")
    janela = P.cross_sectional.janela_reversao

    for tk, ret in retornos_por_ticker.items():
        precos = np.full(n, 100.0)
        precos[-janela:] = 100.0 * np.exp(
            np.linspace(ret / janela, ret, janela)
        )  # move só na janela
        for d, px in zip(datas, precos):
            linhas.append(
                {"ticker": tk, "timestamp": d, "open": px, "high": px * 1.01,
                 "low": px * 0.99, "close": px, "volume": 1e7}
            )
    return pd.DataFrame(linhas)


def _universo(n: int) -> list[str]:
    return [f"TK{i:02d}" for i in range(n)]


def test_o_mais_castigado_vira_compra_e_o_mais_esticado_vira_venda():
    rets = {f"TK{i:02d}": 0.0 for i in range(40)}
    rets["TK00"] = -0.20  # despencou
    rets["TK39"] = +0.20  # disparou

    r = cross_sectional.rank_universo(_painel(rets), DATA, _universo(40), P)
    s = cross_sectional.generate(r, {t: 2.0 for t in rets}, DATA, P, 0.1)

    compras = set(s.loc[s["alert_type"] == AlertType.BUY.value, "ticker"])
    vendas = set(s.loc[s["alert_type"] == AlertType.SELL.value, "ticker"])

    assert "TK00" in compras
    assert "TK39" in vendas
    assert not (compras & vendas)


def test_neutraliza_o_mercado():
    """TODO o mercado cai 10%, e um papel cai 10% igual aos outros.

    Sem neutralizar, ele apareceria como "castigado" e viraria compra — mas ele não destoou
    de nada: caiu junto. Comprar aqui é comprar o índice, não a distorção.
    """
    rets = {f"TK{i:02d}": -0.10 for i in range(40)}  # crash geral, todos iguais
    rets["TK07"] = -0.25  # este SIM destoou

    r = cross_sectional.rank_universo(_painel(rets), DATA, _universo(40), P)

    # Quem caiu junto com o mercado tem excesso ZERO — não é sinal.
    normais = r[r["ticker"] != "TK07"]
    assert normais["excesso"].abs().max() == pytest.approx(0.0, abs=1e-9)

    s = cross_sectional.generate(r, {t: 2.0 for t in rets}, DATA, P, 0.1)
    assert s.loc[s["alert_type"] == AlertType.BUY.value, "ticker"].iloc[0] == "TK07"


def test_rr_minimo_vale_por_construcao():
    rets = {f"TK{i:02d}": np.sin(i) / 10 for i in range(40)}
    r = cross_sectional.rank_universo(_painel(rets), DATA, _universo(40), P)
    s = cross_sectional.generate(r, {t: 2.0 for t in rets}, DATA, P, 0.1)

    risco = (s["trigger_price"] - s["stop_loss_price"]).abs()
    retorno = (s["take_profit_price"] - s["trigger_price"]).abs()

    assert (retorno / risco >= P.risco.rr_minimo - 1e-9).all()


def test_stop_e_alvo_ficam_do_lado_certo_na_compra_e_na_venda():
    rets = {f"TK{i:02d}": (i - 20) / 100 for i in range(40)}
    r = cross_sectional.rank_universo(_painel(rets), DATA, _universo(40), P)
    s = cross_sectional.generate(r, {t: 2.0 for t in rets}, DATA, P, 0.1)

    c = s[s["alert_type"] == AlertType.BUY.value]
    v = s[s["alert_type"] == AlertType.SELL.value]

    assert (c["stop_loss_price"] < c["trigger_price"]).all()
    assert (c["trigger_price"] < c["take_profit_price"]).all()
    assert (v["stop_loss_price"] > v["trigger_price"]).all()
    assert (v["trigger_price"] > v["take_profit_price"]).all()


def test_universo_pequeno_demais_nao_gera_ranking():
    """Rankear 10 papéis e chamar o último de "castigado" é numerologia, não estatística."""
    rets = {f"TK{i:02d}": i / 100 for i in range(10)}

    assert cross_sectional.rank_universo(_painel(rets), DATA, _universo(10), P).empty


def test_o_ranking_nao_enxerga_o_futuro():
    rets = {f"TK{i:02d}": (i - 20) / 100 for i in range(40)}
    painel = _painel(rets)

    # Um cataclismo DEPOIS da data de decisão não pode mudar o ranking daquele dia.
    futuro = painel[painel["timestamp"] == DATA].copy()
    futuro["timestamp"] = DATA + pd.Timedelta(days=1)
    futuro["close"] = 0.01

    a = cross_sectional.rank_universo(painel, DATA, _universo(40), P)
    b = cross_sectional.rank_universo(
        pd.concat([painel, futuro], ignore_index=True), DATA, _universo(40), P
    )

    assert a["ticker"].tolist() == b["ticker"].tolist()


def test_nunca_opera_mais_de_um_terco_do_universo():
    rets = {f"TK{i:02d}": i / 100 for i in range(33)}
    r = cross_sectional.rank_universo(_painel(rets), DATA, _universo(33), P)
    s = cross_sectional.generate(r, {t: 2.0 for t in rets}, DATA, P, 0.1)

    assert len(s) <= 2 * (33 // 3)
