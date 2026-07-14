"""Momentum 12-1.

O teste que mais importa é `test_o_ranking_IGNORA_o_ultimo_mes`. Sem o gap, a reversão de
curto prazo (que já testamos e que não tem borda) entra no ranking e cancela o momentum —
o backtest mediria a soma de duas coisas opostas e devolveria zero, sem que ninguém
percebesse o motivo.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.core.config import Market, Timeframe, load_params
from app.engine import momentum
from app.engine.signals import AlertType

P = load_params(Market.B3, Timeframe.D1)
DATA = pd.Timestamp("2024-06-28", tz="UTC")
N = P.momentum.janela_formacao + P.momentum.gap + 40


def _painel(trajetorias: dict[str, np.ndarray]) -> pd.DataFrame:
    datas = pd.date_range(end=DATA, periods=N, freq="1D", tz="UTC")
    linhas = []
    for tk, precos in trajetorias.items():
        for d, px in zip(datas, precos):
            linhas.append(
                {"ticker": tk, "timestamp": d, "open": px, "high": px * 1.01,
                 "low": px * 0.99, "close": px, "volume": 1e7}
            )
    return pd.DataFrame(linhas)


def _plano(ret_total: float) -> np.ndarray:
    """Trajetória que acumula `ret_total` de forma suave ao longo de toda a série."""
    return 100.0 * np.exp(np.linspace(0, ret_total, N))


def _universo(n: int) -> list[str]:
    return [f"TK{i:02d}" for i in range(n)]


def _long_short():
    return P.model_copy(update={"momentum": P.momentum.model_copy(update={"long_only": False})})


def test_compra_o_VENCEDOR_e_vende_o_PERDEDOR():
    """O oposto da reversão. Aqui o que subiu é comprado, não vendido."""
    p = _long_short()
    traj = {f"TK{i:02d}": _plano(0.0) for i in range(40)}
    traj["TK00"] = _plano(-0.60)  # despencou no ano
    traj["TK39"] = _plano(+0.80)  # disparou no ano

    r = momentum.rank_universo(_painel(traj), DATA, _universo(40), p)
    s = momentum.generate(r, {t: 2.0 for t in traj}, DATA, p, 0.2)

    compras = set(s.loc[s["alert_type"] == AlertType.BUY.value, "ticker"])
    vendas = set(s.loc[s["alert_type"] == AlertType.SELL.value, "ticker"])

    assert "TK39" in compras, "o vencedor do ano tem de ser COMPRADO"
    assert "TK00" in vendas, "o perdedor do ano tem de ser VENDIDO"


def test_long_only_nao_emite_venda():
    """Pessoa física não aluga e shorteia 15 papéis da B3 todo mês. Testar a perna vendida
    seria testar uma operação que nunca seria executada."""
    traj = {f"TK{i:02d}": _plano((i - 20) / 40) for i in range(40)}

    r = momentum.rank_universo(_painel(traj), DATA, _universo(40), P)
    s = momentum.generate(r, {t: 2.0 for t in traj}, DATA, P, 0.2)

    assert P.momentum.long_only
    assert (s["alert_type"] == AlertType.BUY.value).all()


def test_o_ranking_IGNORA_o_ultimo_mes():
    """O "-1" do 12-1, e o detalhe que invalida o teste inteiro se faltar.

    Um papel que subiu o ano todo e desabou SÓ no último mês continua sendo um vencedor de
    momentum. Se o gap não existisse, essa queda recente entraria no ranking, o papel cairia
    para o fundo, e estaríamos medindo reversão de curto prazo com o nome de momentum.
    """
    g = P.momentum.gap
    traj = {f"TK{i:02d}": _plano(0.0) for i in range(40)}

    subiu_e_caiu = _plano(0.80).copy()
    subiu_e_caiu[-g:] *= 0.55  # −45% no último mês, DEPOIS da janela de formação
    traj["TK39"] = subiu_e_caiu

    r = momentum.rank_universo(_painel(traj), DATA, _universo(40), P)
    s = momentum.generate(r, {t: 2.0 for t in traj}, DATA, P, 0.2)

    compras = set(s.loc[s["alert_type"] == AlertType.BUY.value, "ticker"])
    assert "TK39" in compras, "o tombo do último mês não pode entrar no ranking"


def test_o_stop_e_LARGO():
    """Stop apertado mata momentum: a tese precisa de meses. Foi o que estrangulou o
    cross-sectional — 1.096 stops contra 248 alvos.
    """
    assert P.momentum.stop_atr_mult >= 4.0

    traj = {f"TK{i:02d}": _plano((i - 20) / 40) for i in range(40)}
    r = momentum.rank_universo(_painel(traj), DATA, _universo(40), P)
    s = momentum.generate(r, {t: 2.0 for t in traj}, DATA, P, 0.2)

    dist = (s["trigger_price"] - s["stop_loss_price"]).abs()
    assert (dist >= 4.0 * 2.0 - 1e-9).all()


def test_nao_ha_alvo_de_preco_a_saida_e_por_TEMPO():
    """Cortar o vencedor num alvo seria matar justamente o que a estratégia colhe."""
    traj = {f"TK{i:02d}": _plano((i - 20) / 40) for i in range(40)}
    r = momentum.rank_universo(_painel(traj), DATA, _universo(40), P)
    s = momentum.generate(r, {t: 2.0 for t in traj}, DATA, P, 0.2)

    # O alvo é posto tão longe que nunca é tocado — a barreira que vale é a de tempo.
    dist_alvo = (s["take_profit_price"] - s["trigger_price"]).abs()
    dist_stop = (s["trigger_price"] - s["stop_loss_price"]).abs()
    assert (dist_alvo > 50 * dist_stop).all()


def test_neutraliza_o_mercado():
    """Todo mundo subiu 40% no ano: ninguém destoou, ninguém é "vencedor"."""
    traj = {f"TK{i:02d}": _plano(0.40) for i in range(40)}
    traj["TK07"] = _plano(1.20)  # este SIM destoou

    r = momentum.rank_universo(_painel(traj), DATA, _universo(40), P)

    outros = r[r["ticker"] != "TK07"]
    assert outros["excesso"].abs().max() == pytest.approx(0.0, abs=1e-9)
    assert r["ticker"].iloc[-1] == "TK07"  # o topo do ranking


def test_historico_curto_demais_fica_de_fora():
    """Sem 12 meses + o gap, não há como calcular o retorno de formação."""
    curto = pd.DataFrame(
        {
            "ticker": ["X"] * 50,
            "timestamp": pd.date_range(end=DATA, periods=50, freq="1D", tz="UTC"),
            "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1e7,
        }
    )
    assert momentum.rank_universo(curto, DATA, ["X"], P).empty


def test_o_ranking_nao_enxerga_o_futuro():
    traj = {f"TK{i:02d}": _plano((i - 20) / 40) for i in range(40)}
    painel = _painel(traj)

    futuro = painel[painel["timestamp"] == DATA].copy()
    futuro["timestamp"] = DATA + pd.Timedelta(days=1)
    futuro["close"] = 0.01

    a = momentum.rank_universo(painel, DATA, _universo(40), P)
    b = momentum.rank_universo(
        pd.concat([painel, futuro], ignore_index=True), DATA, _universo(40), P
    )
    assert a["ticker"].tolist() == b["ticker"].tolist()
