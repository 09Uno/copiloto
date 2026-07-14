"""Integração com o FinControl (a carteira real).

Este arquivo existe por causa de UM bug que derrubou o código duas vezes, e a segunda foi pior
que a primeira. Ele é o exemplo perfeito do erro que este projeto inteiro combate: **silencioso,
plausível, e devastador.**

O FinControl grava a data em DOIS formatos misturados ('03/11/2025' e '2025-09-05').
"""

from __future__ import annotations

import pandas as pd
import pytest

from app.ingest.fincontrol import _custo_medio, _datas


# --------------------------------------------------------------- o parse da data


def test_os_dois_formatos_convivem():
    s = pd.Series(["03/11/2025", "2025-09-05", "2026-07-14", "23/04/2026"])
    d = _datas(s)

    assert d.notna().all(), "nenhuma linha pode ser descartada"
    assert d.iloc[0] == pd.Timestamp("2025-11-03")  # DD/MM/YYYY
    assert d.iloc[1] == pd.Timestamp("2025-09-05")  # ISO
    assert d.iloc[2] == pd.Timestamp("2026-07-14")
    assert d.iloc[3] == pd.Timestamp("2026-04-23")


def test_o_dayfirst_NAO_pode_embaralhar_a_data_ISO():
    """**O bug que quase passou.**

    `pd.to_datetime(format="mixed", dayfirst=True)` aplica o `dayfirst` TAMBÉM ao ISO: ele leu
    `2025-11-06` como ano-DIA-mês → 11 de junho. As datas ficaram embaralhadas, uma venda do
    TAEE11 foi parar ANTES da compra, o saldo bateu no zero e sobraram 24 cotas FANTASMA na
    carteira. Silencioso, plausível, e completamente errado.
    """
    d = _datas(pd.Series(["2025-11-06"]))

    assert d.iloc[0] == pd.Timestamp("2025-11-06"), "ISO é ano-MÊS-dia, sempre"
    assert d.iloc[0].month == 11
    assert d.iloc[0].day == 6

    # E o `mixed`+`dayfirst` de fato erra — é por isso que não o usamos.
    errado = pd.to_datetime(pd.Series(["2025-11-06"]), format="mixed", dayfirst=True)
    assert errado.iloc[0].month == 6, "documenta o comportamento que nos mordeu"


def test_data_ilegivel_vira_NaT_e_nao_um_chute():
    d = _datas(pd.Series(["", "nao é data", None, "13/13/2025"]))
    assert d.isna().all()


# --------------------------------------------------------------- custo médio


def _tx(linhas: list[tuple[str, str, float, float]]) -> pd.DataFrame:
    """(data, tipo, qtd, preco)"""
    return pd.DataFrame(
        [
            {"data": _datas(pd.Series([d])).iloc[0], "ativo": "X", "tipo": t,
             "qtd": q, "preco": p, "custos": 0.0, "categoria": "Ações"}
            for d, t, q, p in linhas
        ]
    )


def test_a_venda_NAO_mexe_no_custo_medio():
    """O erro mais comum. A venda reduz a QUANTIDADE e realiza lucro/prejuízo — o preço médio
    do que sobra continua o mesmo. Recalcular na venda inflaria ou esvaziaria o yield-on-cost
    sem que nada tivesse acontecido de verdade.
    """
    p = _custo_medio(_tx([
        ("01/01/2026", "C", 100, 10.0),
        ("01/02/2026", "C", 100, 20.0),   # custo médio → 15
        ("01/03/2026", "V", 100, 50.0),   # vende metade CARO: o custo NÃO cai
    ]))[0]

    assert p.quantidade == pytest.approx(100)
    assert p.custo_medio == pytest.approx(15.0)


def test_posicao_zerada_some_da_carteira():
    assert _custo_medio(_tx([
        ("01/01/2026", "C", 100, 10.0),
        ("01/02/2026", "V", 100, 12.0),
    ])) == []


def test_a_ORDEM_das_transacoes_decide_o_resultado():
    """Foi isto que o embaralhamento de datas quebrou: com a venda ANTES da compra, o saldo
    truncava em zero e as compras seguintes deixavam cotas fantasma."""
    correta = _custo_medio(_tx([
        ("10/10/2025", "C", 24, 35.82),
        ("06/11/2025", "V", 24, 40.05),
    ]))
    assert correta == [], "comprou e vendeu tudo: a posição não existe"

    # Com as datas invertidas (o bug), a venda vem primeiro e a compra sobra.
    embaralhada = _custo_medio(_tx([
        ("11/06/2025", "V", 24, 40.05),   # a data que o dayfirst produzia
        ("10/10/2025", "C", 24, 35.82),
    ]))
    assert embaralhada[0].quantidade == 24, "documenta as 24 cotas fantasma do bug"
