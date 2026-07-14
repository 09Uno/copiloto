"""Teste de informação (discriminação das features).

O teste central é `test_o_retorno_futuro_nao_atravessa_a_fronteira_entre_papeis`. O painel vem
com 373 tickers EMPILHADOS; um `shift(-10)` global compara as últimas velas de um papel com as
primeiras do papel seguinte — dividindo o preço de uma ação pelo de outra. Foi o que produziu
"retorno médio de +7,9% em 10 pregões": absurdo o bastante para denunciar o bug, e plausível o
bastante para quase ter sido reportado como descoberta.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backtest import information


def _painel(precos_por_ticker: dict[str, list[float]]) -> pd.DataFrame:
    linhas = []
    for tk, precos in precos_por_ticker.items():
        datas = pd.date_range("2024-01-01", periods=len(precos), freq="1D", tz="UTC")
        for d, px in zip(datas, precos):
            linhas.append(
                {
                    "ticker": tk, "timestamp": d,
                    "open": px, "high": px, "low": px, "close": px,
                    "feat": px,  # feature qualquer, só para o agrupamento por decil
                }
            )
    return pd.DataFrame(linhas)


def test_o_retorno_futuro_nao_atravessa_a_fronteira_entre_papeis():
    """Dois papéis de escalas absurdamente diferentes, ambos PERFEITAMENTE planos.

    O retorno futuro correto é ZERO em todos os casos. Se o shift vazar de um papel para o
    outro, aparecerão retornos gigantes (de 1 para 1000, ou de 1000 para 1).
    """
    n = 600
    painel = _painel({"BARATA": [1.0] * n, "CARA": [1000.0] * n})

    r = information.avaliar(painel, "feat", horizonte=10)

    assert r is not None
    assert r.tabela["retorno_medio"].abs().max() == pytest.approx(0.0, abs=1e-9)


def test_feature_sem_poder_preditivo_da_auc_meio():
    rng = np.random.default_rng(0)
    n = 3000
    precos = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))

    painel = _painel({"X": list(precos)})
    painel["feat"] = rng.normal(0, 1, len(painel))  # feature aleatória, sem relação nenhuma

    r = information.avaliar(painel, "feat", horizonte=10)

    assert abs(r.auc - 0.5) < 0.05
    assert not r.informativa


def test_feature_que_PREVE_de_verdade_e_reconhecida():
    """Uma feature construída para conhecer o futuro tem de acender o alarme.

    É o controle positivo: se nem isto o teste detecta, ele não detectaria informação nenhuma
    e o veredito "sem informação" não valeria nada.
    """
    rng = np.random.default_rng(1)
    n = 3000
    retornos = rng.normal(0, 0.02, n)
    precos = 100 * np.exp(np.cumsum(retornos))

    painel = _painel({"X": list(precos)})
    # A feature É o retorno futuro (com ruído). Trapaça deliberada.
    fwd = pd.Series(precos).shift(-10) / pd.Series(precos) - 1
    painel["feat"] = (fwd + rng.normal(0, 0.005, n)).to_numpy()

    r = information.avaliar(painel.dropna(subset=["feat"]), "feat", horizonte=10)

    assert r.auc > 0.8, "o controle positivo tem de ser detectado"
    assert r.informativa
