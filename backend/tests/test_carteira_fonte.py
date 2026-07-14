"""A fonte de carteira plugável.

O contrato é minúsculo de propósito: uma fonte responde apenas *quais posições, quantidade e
custo médio*. Tudo o mais (preço teto, tese, vigia) já funciona em cima disso — então uma fonte
nova (CSV, corretora) não toca em mais nada.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.carteira import base as cb
from app.carteira.base import Carteira, Fonte, Posicao, vendas_de_acao_no_mes
from app.carteira.fontes import Manual, _classe


def test_o_resto_do_sistema_nao_sabe_a_origem_da_posicao():
    """Uma Carteira do FinControl e uma Manual são indistinguíveis para quem consome."""
    a = Carteira([Posicao("TAEE3", 100, 13.15)], Fonte.MANUAL)
    b = Carteira([Posicao("TAEE3", 100, 13.15)], Fonte.FINCONTROL)

    assert a.de("taee3").custo_medio == b.de("taee3").custo_medio
    assert a.total_investido == b.total_investido


def test_de_ignora_maiuscula_e_espaco():
    c = Carteira([Posicao("GARE11", 504, 8.28)], Fonte.MANUAL)
    assert c.de("  gare11 ") is not None
    assert c.de("VALE3") is None


def test_a_categoria_da_fonte_vira_classe_canonica():
    """Cada fonte fala a sua língua ('Ações', 'Fundos Imobiliários', 'BDRs'). O mapeamento é o
    único lugar que precisa saber disso — o resto do sistema só vê ACAO, FII, BDR."""
    assert _classe("Ações") == "ACAO"
    assert _classe("Fundos Imobiliários") == "FII"
    assert _classe("FIIs") == "FII"
    assert _classe("BDRs") == "BDR"
    assert _classe("Cripto") == "CRIPTO"
    assert _classe("categoria estranha") is None
    assert _classe(None) is None


def test_fonte_manual_nao_busca_nada():
    """As posições vêm do banco (o repo conhece o user_id). A fonte MANUAL não tem o que puxar."""
    assert Manual().puxar({}).posicoes == []
    assert Manual().campos_config() == {}


def test_registro_e_lookup():
    cb.registrar(Manual())
    assert cb.para(Fonte.MANUAL) is not None
    assert Fonte.MANUAL in cb.disponiveis()


# --------------------------------------------------------------- isenção de IR


def test_isencao_vale_so_para_ACAO():
    """FII paga 20% sempre, sem isenção. Misturar as duas categorias faz o usuário achar que
    está isento quando vai pagar — ou no limite quando não está."""
    vendas = [
        (date(2026, 7, 3), "Ações", 12_000.0),
        (date(2026, 7, 10), "Ações", 5_000.0),
        (date(2026, 7, 15), "Fundos Imobiliários", 30_000.0),  # NÃO conta
    ]
    total = vendas_de_acao_no_mes(vendas, date(2026, 7, 20))

    assert total == pytest.approx(17_000.0), "só as vendas de ação entram na isenção"


def test_isencao_so_conta_o_mes_corrente():
    vendas = [
        (date(2026, 6, 30), "Ações", 19_000.0),   # mês passado
        (date(2026, 7, 2), "Ações", 3_000.0),
    ]
    assert vendas_de_acao_no_mes(vendas, date(2026, 7, 20)) == pytest.approx(3_000.0)
