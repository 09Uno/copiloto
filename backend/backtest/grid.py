"""Grid search com validação FORA da amostra.

A regra que torna isto legítimo: **o grid escolhe o vencedor olhando SÓ o in-sample.** O
out-of-sample é aberto uma única vez, no fim, para julgar o escolhido.

Escolher o melhor pelo out-of-sample é a fraude mais comum do backtest — e a mais fácil de
cometer sem perceber. Bastam algumas centenas de combinações para que a sorte produza uma que
parece genial no período de teste. O out-of-sample deixa de ser teste e vira mais um conjunto
de treino, e o backtest passa a medir a sorte, não a estratégia.

Por isso `melhor_in_sample` é o único caminho de escolha, e `julgar` só é chamado depois.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from typing import Callable

import pandas as pd

from app.core.config import Market, Params, Timeframe
from backtest.metrics import Metricas
from backtest.runner import Resultado


@dataclass
class Ponto:
    config: dict
    dentro: Metricas | None
    fora: Metricas | None


def _aplicar(p: Params, config: dict) -> Params:
    """Params é imutável (frozen) — cada ponto do grid vira uma cópia nova."""
    d = p.model_dump()
    for caminho, valor in config.items():
        secao, chave = caminho.split(".")
        d[secao][chave] = valor
    return Params.model_validate(d)


def rodar(
    p_base: Params,
    espaco: dict[str, list],
    executar: Callable[[Params], Resultado],
) -> list[Ponto]:
    chaves = list(espaco)
    combinacoes = list(itertools.product(*(espaco[k] for k in chaves)))

    pontos: list[Ponto] = []
    for valores in combinacoes:
        config = dict(zip(chaves, valores))
        try:
            r = executar(_aplicar(p_base, config))
        except Exception:  # noqa: BLE001 — combinação inválida não derruba o grid
            continue
        pontos.append(Ponto(config=config, dentro=r.dentro, fora=r.fora))

    return pontos


def melhor_in_sample(pontos: list[Ponto], min_trades: int = 100) -> Ponto | None:
    """Escolhe pelo IN-SAMPLE. Nunca espiar o out-of-sample para decidir."""
    validos = [
        pt for pt in pontos
        if pt.dentro is not None and pt.dentro.n >= min_trades
    ]
    if not validos:
        return None
    return max(validos, key=lambda pt: pt.dentro.expectancia_r)


def tabela(pontos: list[Ponto], top: int = 12) -> pd.DataFrame:
    linhas = []
    for pt in pontos:
        if pt.dentro is None:
            continue
        linhas.append(
            {
                **pt.config,
                "n_dentro": pt.dentro.n,
                "exp_dentro": round(pt.dentro.expectancia_r, 4),
                "pf_dentro": round(pt.dentro.profit_factor, 2),
                "n_fora": pt.fora.n if pt.fora else 0,
                "exp_fora": round(pt.fora.expectancia_r, 4) if pt.fora else None,
                "pf_fora": round(pt.fora.profit_factor, 2) if pt.fora else None,
            }
        )
    if not linhas:
        return pd.DataFrame()
    return (
        pd.DataFrame(linhas)
        .sort_values("exp_dentro", ascending=False)
        .head(top)
        .reset_index(drop=True)
    )
