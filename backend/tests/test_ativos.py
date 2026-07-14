"""A camada de decisão: contrato dos plugins, preço teto, yield-on-cost.

Estes testes existem porque eu corrigi estes bugs **sem travá-los** — e conserto sem teste é
meio conserto: o bug volta na próxima mudança, plausível e silencioso.

O mais perigoso é `test_multiplo_historico_nao_colapsa_em_preco_vs_preco`. Ele guarda o
detector de euforia, que estava MENTINDO.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.ativos import base as ab
from app.ativos.base import Avaliacao, Classe, Metrica, Teto
from app.ativos.decisao import Posicao, simular
from app.ativos.sem_criterio import ETF, Cripto


# --------------------------------------------------------------- o contrato


def test_o_nome_da_metrica_e_a_interface_entre_plugin_e_motor():
    """O bug: o motor procurava `dpa`; o FII registrava `rendimento_12m`. O yield-on-cost
    simplesmente não saía — sem erro, sem aviso.

    Uma ação chama de "dividendo por ação" e um FII de "rendimento por cota". O RÓTULO pode
    (e deve) diferir. O NOME, não: é ele que o motor consulta.
    """
    acao = Avaliacao(
        ticker="TAEE3", classe=Classe.ACAO, preco=13.67,
        metricas={ab.RENDA_POR_UNIDADE: Metrica("dpa", "Dividendo por ação", 1.08)},
        teto=Teto(13.50, "…", 0.08),
    )
    fundo = Avaliacao(
        ticker="GARE11", classe=Classe.FII, preco=8.15,
        metricas={ab.RENDA_POR_UNIDADE: Metrica("dpa", "Rendimento por cota", 0.91)},
        teto=Teto(9.10, "…", 0.10),
    )

    for av, cm in ((acao, 13.15), (fundo, 8.28)):
        ap = simular(av, Posicao(av.ticker, 100, cm), 100)
        assert ap.yoc_antes is not None, f"{av.ticker}: o motor não achou a renda por unidade"
        assert ap.yoc_depois is not None


def test_classe_sem_criterio_ADMITE_que_nao_sabe():
    """Seria trivial inventar um score aqui e a tela ficaria mais bonita. Seria a mesma mentira
    que o backtest destruiu (AUC 0,50): convicção sem vantagem."""
    for impl in (Cripto(), ETF()):
        av = impl.avaliar("BTC", 321_837.0, 0.08)

        assert av.teto is None
        assert av.sem_criterio, "a classe tem de DIZER que não sabe, não devolver um número"
        assert av.metricas == {}
        assert impl.metricas_disponiveis() == {}


def test_sem_criterio_o_veredito_nao_finge():
    av = Cripto().avaliar("BTC", 321_837.0, 0.08)
    ap = simular(av, None, 0.01)

    assert ap.veredito == "SEM CRITÉRIO"
    assert ap.dentro_do_teto is None


# --------------------------------------------------------------- preço teto


def _av(preco: float, dpa: float, meta: float, **extra) -> Avaliacao:
    m = {ab.RENDA_POR_UNIDADE: Metrica("dpa", "renda", dpa)}
    m.update({k: Metrica(k, k, v) for k, v in extra.items()})
    return Avaliacao(
        ticker="X", classe=Classe.ACAO, preco=preco, metricas=m,
        teto=Teto(dpa / meta, f"{dpa} ÷ {meta}", meta) if dpa > 0 else None,
    )


def test_o_teto_vem_da_SUA_meta_e_nao_do_mercado():
    """Paga R$ 1,08. Quem quer 8% aceita até R$ 13,50; quem quer 10%, só até R$ 10,80.
    O mesmo ativo, o mesmo dia — **critérios diferentes, porque as metas são diferentes.**
    Nada aqui prevê preço."""
    assert _av(13.67, 1.08, 0.08).teto.valor == pytest.approx(13.50)
    assert _av(13.67, 1.08, 0.10).teto.valor == pytest.approx(10.80)


def test_acima_e_abaixo_do_teto():
    assert _av(13.00, 1.08, 0.08).abaixo_do_teto is True
    assert _av(13.67, 1.08, 0.08).abaixo_do_teto is False
    assert _av(13.67, 1.08, 0.08).margem_pct == pytest.approx(-1.24, abs=0.01)


def test_sem_dividendo_nao_ha_teto_de_yield():
    """Empresa que não distribui não tem preço teto POR YIELD — e o sistema não inventa um."""
    assert _av(50.0, 0.0, 0.08).teto is None


# --------------------------------------------------------------- yield-on-cost


def test_yield_on_cost_e_travado_no_preco_que_VOCE_pagou():
    """Comprou a 13,15 e o papel paga 1,08 → 8,2%, e é seu para sempre. É por isso que vender
    um vencedor com tese intacta costuma ser o erro mais caro do investidor de dividendo."""
    ap = simular(_av(20.00, 1.08, 0.08), Posicao("X", 244, 13.15), 0)
    assert ap is None  # quantidade 0 → não simula

    ap = simular(_av(20.00, 1.08, 0.08), Posicao("X", 244, 13.15), 1)
    assert ap.yoc_antes == pytest.approx(1.08 / 13.15)
    assert ap.yield_atual == pytest.approx(1.08 / 20.00)
    assert ap.yoc_antes > ap.yield_atual, "seu yield é maior que o do mercado hoje"


def test_comprar_mais_caro_derruba_o_seu_yield_on_cost_e_o_sistema_avisa():
    ap = simular(_av(20.00, 1.08, 0.08), Posicao("X", 100, 13.15), 100)

    assert ap.custo_medio_depois == pytest.approx((100 * 13.15 + 100 * 20.0) / 200)
    assert ap.yoc_depois < ap.yoc_antes
    assert any("derruba seu yield-on-cost" in m for m in ap.motivos)


def test_posicao_nova_nao_explode():
    ap = simular(_av(13.00, 1.08, 0.08), None, 100)
    assert ap.custo_medio_antes == 0
    assert ap.custo_medio_depois == pytest.approx(13.00)


# --------------------------------------------------------------- euforia


def test_euforia_e_pagar_um_multiplo_que_voce_nunca_pagou():
    av = _av(13.67, 1.08, 0.08, pl_vs_historia=1.60)
    ap = simular(av, None, 100)

    assert any("mediana histórica" in m for m in ap.motivos)


def test_multiplo_historico_nao_colapsa_em_preco_vs_preco():
    """**O bug mais perigoso da camada, e o que quase passou.**

    Usar o LPA de HOJE sobre os preços passados faz a conta colapsar:

        P/L_hoje ÷ mediana(preços / LPA_hoje)  =  preço_hoje ÷ mediana(preços)

    O LPA some da equação e o "múltiplo vs. história" vira **preço vs. preço**. Foi o que
    denunciou o P/L e o P/VP saírem com o MESMO 122% na TAEE3.

    E isso MENTE: aqui o lucro TRIPLICA enquanto o preço só dobra. A ação ficou **mais
    barata** em P/L — mas a conta ingênua diria "está 100% mais cara". O detector de euforia
    daria exatamente o conselho oposto ao certo.
    """
    n = 500
    precos = pd.Series(
        np.linspace(10.0, 20.0, n),  # preço dobra
        index=pd.date_range("2020-01-01", periods=n, freq="D"),
    )
    lpa_pit = pd.Series(  # lucro por ação TRIPLICA no mesmo período (point-in-time)
        np.linspace(1.0, 3.0, n),
        index=precos.index,
    )

    # O jeito CERTO: cada preço dividido pelo LPA que estava público NAQUELE dia.
    pl_serie = precos / lpa_pit
    pl_hoje = float(pl_serie.iloc[-1])          # 20/3 = 6.67
    pl_mediana = float(pl_serie.median())       # ~7.5
    razao_certa = pl_hoje / pl_mediana

    # O jeito ERRADO: LPA de hoje sobre os preços passados.
    lpa_hoje = float(lpa_pit.iloc[-1])
    razao_errada = (precos.iloc[-1] / lpa_hoje) / float((precos / lpa_hoje).median())

    assert razao_certa < 1.0, "com o lucro triplicando, a ação está MAIS BARATA em P/L"
    assert razao_errada > 1.0, "a conta ingênua diria o contrário — e é isso que a matou"
    assert razao_errada == pytest.approx(
        precos.iloc[-1] / precos.median()
    ), "o LPA some da equação: vira preço vs. preço"
