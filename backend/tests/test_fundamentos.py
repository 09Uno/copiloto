"""Fundamentos da CVM.

O teste central é `test_o_primeiro_trimestre_nao_e_contado_duas_vezes`. A maioria das empresas
só publica o ACUMULADO do ano no fluxo de caixa, e reconstruir o trimestre por diferença é a
única saída. Errar essa diferença por um item — deixar o Q1 fora da série acumulada — faz o
primeiro trimestre entrar duas vezes e propaga o erro pelo ano inteiro.

Foi o que inflou o dividendo da VALE (payout de 249%) e do ITAÚ (111%). E o DPA é o CORAÇÃO do
preço teto: se ele sai 2x alto, o teto sai 2x alto e o sistema manda comprar a qualquer preço.
"""

from __future__ import annotations

import pandas as pd
import pytest

from app.engine import fundamentos as fd


def _linhas(registros: list[dict]) -> pd.DataFrame:
    """registros: (dt_ini, dt_fim, valor, [conta], [descricao])"""
    return pd.DataFrame(
        [
            {
                "conta": r.get("conta", "3.11"),
                "descricao": r.get("descricao", "Lucro/Prejuízo Consolidado do Período"),
                "dt_ini": pd.Timestamp(r["dt_ini"]),
                "dt_fim": pd.Timestamp(r["dt_fim"]),
                "valor": r["valor"],
            }
            for r in registros
        ]
    )


# ------------------------------------------------- reconstrução do trimestre


def test_o_primeiro_trimestre_nao_e_contado_duas_vezes():
    """A empresa só publica ACUMULADO. Q1=10, Q2=20, Q3=30, Q4=40.

    Se o Q1 ficar de fora da série acumulada, `Q2 = acum(jun) − 0 = 30` (Q1+Q2) em vez de 20.
    O ano vira 130 em vez de 100 — e o dividendo aparece 30% maior do que é.
    """
    df = _linhas([
        {"dt_ini": "2024-01-01", "dt_fim": "2024-03-31", "valor": 10},   # acum Q1
        {"dt_ini": "2024-01-01", "dt_fim": "2024-06-30", "valor": 30},   # acum H1
        {"dt_ini": "2024-01-01", "dt_fim": "2024-09-30", "valor": 60},   # acum 9M
        {"dt_ini": "2024-01-01", "dt_fim": "2024-12-31", "valor": 100},  # acum ano (DFP)
    ])

    tri = fd._fluxo_trimestral(df, "3.11")

    assert tri.tolist() == pytest.approx([10, 20, 30, 40])
    assert tri.sum() == pytest.approx(100), "o ano tem de fechar no valor publicado"


def test_o_quarto_trimestre_nasce_da_diferenca_com_o_anual():
    """O 4º tri NÃO EXISTE no ITR — a CVM só recebe ITR de Q1, Q2 e Q3. Ele vem do DFP anual.

    Sem reconstruí-lo, "últimos 12 meses" viraria 9 meses: o lucro sairia ~25% menor,
    para sempre e em silêncio.
    """
    df = _linhas([
        {"dt_ini": "2024-01-01", "dt_fim": "2024-03-31", "valor": 25},
        {"dt_ini": "2024-01-01", "dt_fim": "2024-06-30", "valor": 50},
        {"dt_ini": "2024-01-01", "dt_fim": "2024-09-30", "valor": 75},
        {"dt_ini": "2024-01-01", "dt_fim": "2024-12-31", "valor": 120},  # DFP
    ])

    tri = fd._fluxo_trimestral(df, "3.11")

    assert len(tri) == 4
    assert tri.iloc[-1] == pytest.approx(45), "Q4 = 120 − 75"


def test_o_trimestre_publicado_pela_empresa_tem_precedencia():
    """A DRE costuma trazer acumulado E isolado. O número da empresa vale mais que o nosso."""
    df = _linhas([
        {"dt_ini": "2024-01-01", "dt_fim": "2024-03-31", "valor": 10},
        {"dt_ini": "2024-01-01", "dt_fim": "2024-06-30", "valor": 30},
        {"dt_ini": "2024-04-01", "dt_fim": "2024-06-30", "valor": 21},  # ← isolado, publicado
    ])

    tri = fd._fluxo_trimestral(df, "3.11")

    assert tri.loc[pd.Timestamp("2024-06-30")] == pytest.approx(21)


def test_cada_ano_recomeca_do_zero():
    """O acumulado zera em janeiro. Diferenciar entre anos daria um Q1 negativo gigante."""
    df = _linhas([
        {"dt_ini": "2024-01-01", "dt_fim": "2024-12-31", "valor": 100},
        {"dt_ini": "2025-01-01", "dt_fim": "2025-03-31", "valor": 30},
    ])

    tri = fd._fluxo_trimestral(df, "3.11")

    assert tri.loc[pd.Timestamp("2025-03-31")] == pytest.approx(30)


# ------------------------------------------------- as contas certas


def test_o_lucro_e_achado_pela_descricao_em_qualquer_setor():
    """É 3.11 na Petrobras e 3.09 no Itaú; "Lucro/Prejuízo" na Vale e "Lucro OU Prejuízo" no
    Bradesco. Buscar por código deixaria o maior banco do país SEM LUCRO — sem erro nenhum."""
    import re

    for desc in (
        "Lucro/Prejuízo Consolidado do Período",       # Petrobras, Vale
        "Lucro ou Prejuízo Líquido do Período",        # Bradesco, Banco do Brasil
        "Lucro ou Prejuízo Líquido Consolidado do Período",
        "Lucro/Prejuízo do Período",                   # Sanepar (demonstração individual)
    ):
        assert re.search(fd.RE_LUCRO, desc, re.IGNORECASE), desc

    # E NÃO pode capturar estas:
    for desc in (
        "Lucro ou Prejuízo das Operações Continuadas",
        "Lucro ou Prejuízo antes das Participações e Contribuições Estatutárias",
        "Lucro Básico por Ação",
    ):
        assert not re.search(fd.RE_LUCRO, desc, re.IGNORECASE), desc


def test_dividendo_recebido_de_controlada_nao_conta_como_pago():
    """A TAESA e o WEG RECEBEM dividendo de controladas (entrada) e PAGAM ao acionista (saída).
    Somar os dois os faz se CANCELAR — o payout da Taesa despencava para 19% (o real é ~85%).
    """
    df = pd.DataFrame([
        {"conta": "6.01.02.04", "descricao": "Dividendos recebidos de controladas",
         "dt_ini": pd.Timestamp("2024-01-01"), "dt_fim": pd.Timestamp("2024-03-31"),
         "valor": +500},
        {"conta": "6.03.07", "descricao": "Pagamento de dividendos e JCP",
         "dt_ini": pd.Timestamp("2024-01-01"), "dt_fim": pd.Timestamp("2024-03-31"),
         "valor": -800},
    ])

    so_pago = df[df["conta"].str.startswith(fd.GRUPO_FINANCIAMENTO)]
    tri = fd._fluxo_trimestral(so_pago, None, fd.RE_DIVIDENDO)

    assert tri.iloc[0] == pytest.approx(-800), "o recebido não pode abater o pago"


def test_dividendo_a_nao_controlador_nao_e_seu():
    """A VALE paga dividendo aos "acionistas NÃO CONTROLADORES" — o minoritário das
    SUBSIDIÁRIAS dela, não o acionista da Vale. Somar isso inflava o payout para 249%."""
    import re

    assert re.search(fd.RE_NAO_CONTROLADOR,
                     "Dividendos e JCP pagos aos acionistas não controladores",
                     re.IGNORECASE)
    assert not re.search(fd.RE_NAO_CONTROLADOR,
                         "Dividendos/JCP Pagos a Acionistas", re.IGNORECASE)


# ------------------------------------------------- escala das ações


def test_a_escala_das_acoes_e_corrigida():
    """A CVM não é consistente: a PETROBRAS reporta 7.442.231.382 (unidades) e a TAESA reporta
    590.714 (milhares). Sem detectar, o LPA da Taesa sai 1000x inflado (saía R$ 1.517)."""
    assert fd._normalizar_acoes(7_442_231_382) == pytest.approx(7_442_231_382)  # unidades
    assert fd._normalizar_acoes(1_033_497) == pytest.approx(1_033_497_000)      # milhares
    assert fd._normalizar_acoes(0) is None
    assert fd._normalizar_acoes(None) is None
