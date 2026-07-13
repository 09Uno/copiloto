"""Ajuste por evento corporativo.

Sem isto, o COTAHIST (que traz preço BRUTO) faz um desdobramento 1:2 parecer um crash de
-50%, e o motor dispara uma compra enorme e falsa. É o bug mais caro que este projeto pode ter,
porque ele não parece um bug: parece um sinal.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.ingest import corporate


def _serie(precos: list[float], inicio: str = "2024-01-01") -> pd.DataFrame:
    n = len(precos)
    return pd.DataFrame(
        {
            "timestamp": pd.date_range(inicio, periods=n, freq="1D", tz="UTC"),
            "open": precos,
            "high": precos,
            "low": precos,
            "close": precos,
            "volume": [1e6] * n,
        }
    )


def _evento(data: str, fator: float) -> pd.Series:
    return pd.Series([fator], index=pd.DatetimeIndex([data], tz="UTC"), name="fator")


def test_desdobramento_1_para_2_deixa_a_serie_continua():
    # O papel valia 100 e passa a valer 50 no dia ex. Economicamente NADA aconteceu.
    df = _serie([100, 100, 50, 50])
    ev = _evento("2024-01-03", 2.0)  # dia ex = 3ª vela

    out = corporate.adjust(df, ev)

    # Tudo antes do ex vira 50 → a série fica plana, como deve ser.
    assert out["close"].tolist() == pytest.approx([50, 50, 50, 50])


def test_data_do_evento_com_HORA_nao_desloca_o_ajuste_em_um_dia():
    """O bug real: o Yahoo carimba o split às 10:00 de Brasília (13:00 UTC), o pregão do
    COTAHIST é 00:00 UTC. Sem normalizar a data, o PRÓPRIO dia ex — que já negocia no preço
    pós-split — é dividido de novo, e nasce um salto fantasma de +100% exatamente na data
    do desdobramento. Foi assim que o WEGE3 apareceu com +100,6% em 2015-04-02.
    """
    df = _serie([100, 100, 50, 50])
    ev = pd.Series(
        [2.0],
        index=pd.DatetimeIndex(["2024-01-03 13:00:00"], tz="UTC"),  # ← com hora
        name="fator",
    )

    out = corporate.adjust(df, ev)
    retornos = out["close"].pct_change().dropna()

    assert out["close"].tolist() == pytest.approx([50, 50, 50, 50])
    assert (retornos.abs() < 1e-9).all(), "não pode sobrar salto na data do evento"


def test_grupamento_reverso_tambem_e_tratado():
    # Grupamento 8:1 — o preço MULTIPLICA. Fator do Yahoo vem como 0.125.
    df = _serie([1.0, 1.0, 8.0, 8.0])
    out = corporate.adjust(df, _evento("2024-01-03", 0.125))

    assert out["close"].tolist() == pytest.approx([8, 8, 8, 8])


def test_eventos_encadeados_multiplicam():
    # Dois desdobramentos 1:2: o preço mais antigo tem de ser dividido por 4.
    df = _serie([100, 50, 25])
    ev = pd.Series(
        [2.0, 2.0],
        index=pd.DatetimeIndex(["2024-01-02", "2024-01-03"], tz="UTC"),
        name="fator",
    )

    assert corporate.adjust(df, ev)["close"].tolist() == pytest.approx([25, 25, 25])


def test_volume_financeiro_nao_e_ajustado():
    """Volume em R$ é INVARIANTE a desdobramento: o dinheiro negociado não muda porque o
    papel virou duas partes. (Volume em QUANTIDADE mudaria — por isso lemos VOLTOT.)
    """
    df = _serie([100, 50])
    out = corporate.adjust(df, _evento("2024-01-02", 2.0))

    assert out["volume"].tolist() == df["volume"].tolist()


def test_sem_evento_a_serie_passa_intacta():
    df = _serie([100, 101, 102])
    assert corporate.adjust(df, corporate._vazio())["close"].tolist() == [100, 101, 102]


def test_o_alarme_denuncia_salto_sem_evento_conhecido():
    """Última linha de defesa: papel cujo evento o Yahoo desconhece. Aceitar o salto em
    silêncio faria o motor tratar um grupamento como um crash real.
    """
    df = _serie([100, 100, 50, 50])  # despenca 50% sem evento cadastrado

    j = corporate.jumps_nao_explicados(df, corporate._vazio())

    assert len(j) == 1
    assert j["variacao_pct"].iloc[0] == pytest.approx(-50.0)


def test_o_alarme_fica_calado_quando_o_evento_explica_o_salto():
    df = _serie([100, 100, 50, 50])
    ev = _evento("2024-01-03", 2.0)

    ajustado = corporate.adjust(df, ev)

    assert len(corporate.jumps_nao_explicados(ajustado, ev)) == 0


def test_oscilacao_normal_nao_dispara_o_alarme():
    rng = np.random.default_rng(1)
    df = _serie(list(100 * np.exp(np.cumsum(rng.normal(0, 0.02, 200)))))

    assert len(corporate.jumps_nao_explicados(df, corporate._vazio())) == 0


# ----------------------------------------------------- reconciliação (evento omitido)


def _referencia(precos: list[float], inicio: str = "2024-01-01") -> pd.Series:
    idx = pd.date_range(inicio, periods=len(precos), freq="1D", tz="UTC")
    return pd.Series(precos, index=idx, dtype=float)


def test_reconcile_encontra_o_evento_que_a_lista_do_yahoo_OMITE():
    """O caso MGLU3: a razão fica em 1,069 por anos e cai para 1,000 — existe um evento de
    6,9% que o Yahoo aplica no preço dele mas não declara na lista de splits.
    """
    n = 120
    ref = _referencia([100.0] * n)  # referência plana e já ajustada
    # A nossa série está 6,9% ACIMA da referência na primeira metade: falta ajustar por
    # um evento de fator 1.069 ocorrido no meio.
    nossa = _serie([106.9] * 60 + [100.0] * 60)

    faltantes = corporate.reconcile(nossa, ref)

    assert len(faltantes) == 1
    assert float(faltantes.iloc[0]) == pytest.approx(1.069, rel=1e-3)

    # E o ajuste com o evento recuperado deixa a série contínua.
    corrigida = corporate.adjust(nossa, faltantes)
    assert corrigida["close"].std() == pytest.approx(0.0, abs=1e-6)


def test_reconcile_ignora_ruido_de_arredondamento_de_centavos():
    """O bug que a primeira versão tinha: numa ação de R$ 1,00 um centavo já é 1%, e comparar
    velas vizinhas detectava "evento" o tempo todo. Compor 10.867 fatores espúrios destruiu a
    série (o erro do PETR4 subiu de 0,10% para 2,19%).
    """
    rng = np.random.default_rng(3)
    n = 200
    verdadeiro = 100 * np.exp(np.cumsum(rng.normal(0, 0.015, n)))
    ref = _referencia(list(verdadeiro))
    # Mesma série, só que arredondada a centavos → razão treme, mas não muda de patamar.
    nossa = _serie(list(np.round(verdadeiro, 2)))

    assert len(corporate.reconcile(nossa, ref)) == 0


def test_reconcile_nao_inventa_evento_quando_as_series_ja_batem():
    ref = _referencia([100.0, 101.0, 102.0] * 40)
    nossa = _serie([100.0, 101.0, 102.0] * 40)

    assert len(corporate.reconcile(nossa, ref)) == 0


def test_reconcile_sem_referencia_nao_faz_nada():
    assert len(corporate.reconcile(_serie([100.0] * 100), pd.Series(dtype=float))) == 0
