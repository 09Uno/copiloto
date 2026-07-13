"""Avaliação fundamentalista.

Os testes que mais importam são os que impedem o modelo de fingir convicção: Graham sobre
prejuízo, Gordon com crescimento próximo do desconto, e a armadilha de valor (barato porque
está quebrando, não porque está descontado).
"""

from __future__ import annotations

import pandas as pd
import pytest

from app.engine import value
from app.ingest.fundamentals import Fundamentos


def test_graham_e_a_raiz_de_22_5_lpa_vpa():
    # LPA 2, VPA 20 → √(22.5 × 2 × 20) = √900 = 30
    assert value.graham(2.0, 20.0) == pytest.approx(30.0)


def test_graham_nao_avalia_empresa_que_da_prejuizo():
    """Raiz de número negativo não é "empresa barata" — é empresa que perde dinheiro."""
    assert value.graham(-1.0, 20.0) is None
    assert value.graham(2.0, -5.0) is None


def test_gordon_recusa_crescimento_perto_do_desconto():
    """g → k faz o valor explodir. Um modelo que devolve "infinito" porque alguém supôs
    crescimento eterno de 9,5% com desconto de 10% não é modelo, é divisão por quase-zero.
    """
    assert value.gordon(1.0, 0.10, 0.095) is None  # folga de 0,5% → recusa
    assert value.gordon(1.0, 0.10, 0.03) == pytest.approx(1 / 0.07)


def test_pl_historico_compara_o_papel_com_ELE_MESMO():
    # O P/L da Vale contra o do Itaú não diz nada: setores têm múltiplos diferentes.
    precos = pd.Series([10.0, 20.0, 30.0])
    assert value.pl_historico(precos, lpa=2.0) == pytest.approx(10.0)  # mediana(5,10,15)


def test_acao_barata_e_boa_tira_score_alto():
    f = Fundamentos(
        ticker="X", preco=20.0, lpa=3.0, vpa=25.0,  # graham = √(22.5·3·25) ≈ 41
        roe=0.22, pl=6.7, dividendo_yield=0.06, payout=0.4,
    )
    a = value.avaliar(f)

    assert a.margem_graham > 50  # negociando MUITO abaixo do intrínseco
    assert a.score >= 60


def test_armadilha_de_valor_barato_mas_ruim_nao_tira_score_alto():
    """Uma empresa pode estar 60% abaixo de Graham porque o lucro vai evaporar.
    Desconto sem qualidade não é oportunidade — é aviso.
    """
    boa = Fundamentos(ticker="BOA", preco=20.0, lpa=3.0, vpa=25.0, roe=0.22, pl=6.7)
    ruim = Fundamentos(ticker="RUIM", preco=20.0, lpa=3.0, vpa=25.0, roe=0.01, pl=6.7)

    assert value.avaliar(ruim).score < value.avaliar(boa).score


def test_alerta_contabil_corroi_o_score():
    limpa = Fundamentos(ticker="A", preco=20.0, lpa=3.0, vpa=25.0, roe=0.22, pl=6.7)
    suspeita = Fundamentos(
        ticker="B", preco=20.0, lpa=3.0, vpa=25.0, roe=0.22, pl=6.7,
        payout=1.8,  # distribui quase o dobro do que lucra
    )

    a = value.avaliar(suspeita)
    assert any("payout" in x for x in a.alertas)
    assert a.score < value.avaliar(limpa).score


def test_pl_baixo_demais_vira_alerta_e_nao_entusiasmo():
    f = Fundamentos(ticker="X", preco=20.0, lpa=3.0, vpa=25.0, roe=0.2, pl=2.5)
    a = value.avaliar(f)

    assert any("não-recorrente" in x for x in a.alertas)


def test_sem_lpa_ou_vpa_nao_ha_avaliacao():
    assert value.avaliar(Fundamentos(ticker="X", preco=10.0)) is None
    assert value.avaliar(Fundamentos(ticker="X", preco=10.0, lpa=1.0)) is None
