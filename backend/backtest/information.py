"""Teste de INFORMAÇÃO — a pergunta certa, que o backtest de lucro não responde.

O backtest mede: *"esse sinal ganha dinheiro sozinho?"* — resposta: não.
Este módulo mede: *"esse sinal carrega informação que ajuda a decidir?"* — outra pergunta.

São diferentes. Um sinal pode ter expectância zero como robô (o custo come, o stop está errado,
o alvo é simétrico) e ainda assim DISCRIMINAR: "quando isso acontece, o papel sobe 58% das
vezes em vez de 50%". Isso é informação real, e um humano faz com ela o que um robô não faz —
segura mais, dimensiona diferente, cruza com o balanço, ignora quando a notícia contradiz.

**O teste:** agrupa os setups por decil da feature e olha o desfecho médio de cada decil.

  · decil de cima acerta 60% e o de baixo 40%  → HÁ informação; a probabilidade é honesta.
  · todos os decis dão ~50%                    → NÃO há informação. Mostrar "68% de chance"
                                                 na tela seria mentira com cara de ciência —
                                                 pior do que não ter ferramenta nenhuma.

É também o **portão honesto do machine learning**: se as features não discriminam, nenhum
XGBoost inventa informação que não está no dado. Só faz sentido treinar se houver o que aprender.

A relação precisa se sustentar FORA da amostra. Uma relação que só existe no passado que a
gente olhou é uma coincidência com nome bonito.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from app.core.config import Params


@dataclass
class Discriminacao:
    feature: str
    n: int
    tabela: pd.DataFrame  # decil → taxa de alta, retorno médio à frente
    auc: float            # 0.5 = moeda honesta; >0.55 já é informação de verdade
    spread: float         # retorno médio do decil de cima − o do decil de baixo (p.p.)

    @property
    def informativa(self) -> bool:
        """AUC acima de 0.53 já é raro e útil em finanças. Abaixo disso é ruído."""
        return abs(self.auc - 0.5) > 0.03


def _auc(score: np.ndarray, alvo_binario: np.ndarray) -> float:
    """AUC via estatística de Mann-Whitney — não precisa de sklearn, e é exato."""
    n1 = int(alvo_binario.sum())
    n0 = len(alvo_binario) - n1
    if n1 == 0 or n0 == 0:
        return 0.5
    ordem = pd.Series(score).rank().to_numpy()
    return float((ordem[alvo_binario == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def avaliar(
    df: pd.DataFrame,
    feature: str,
    horizonte: int,
    n_decis: int = 10,
) -> Discriminacao | None:
    """`df` precisa das features e de `close`. Calcula o retorno À FRENTE e mede a relação.

    O retorno futuro é olhado a partir da vela SEGUINTE (entrada na abertura seguinte, como no
    backtest): usar o próprio fechamento que gerou o setup seria lookahead.
    """
    d = df.dropna(subset=[feature, "close"]).copy()
    if len(d) < 500 or "ticker" not in d.columns:
        return None

    # O shift TEM de ser POR PAPEL. O painel vem empilhado (373 tickers um embaixo do
    # outro); um shift global compara as últimas velas da PETR4 com as primeiras da VALE3 —
    # divide o preço de uma ação pelo de outra. O resultado foram retornos médios de +7,9%
    # em 10 pregões: absurdo o bastante para denunciar o bug, e plausível o bastante para
    # ter sido reportado como descoberta.
    d = d.sort_values(["ticker", "timestamp"])
    g = d.groupby("ticker", sort=False)
    entrada = g["open"].shift(-1)
    saida = g["close"].shift(-horizonte)

    d["fwd"] = (saida / entrada - 1.0) * 100.0
    d = d.dropna(subset=["fwd"])
    if len(d) < 500:
        return None

    d["decil"] = pd.qcut(d[feature], n_decis, labels=False, duplicates="drop")

    tabela = (
        d.groupby("decil")
        .agg(
            n=("fwd", "size"),
            faixa_min=(feature, "min"),
            faixa_max=(feature, "max"),
            taxa_alta=("fwd", lambda x: 100.0 * (x > 0).mean()),
            retorno_medio=("fwd", "mean"),
        )
        .reset_index()
    )

    auc = _auc(d[feature].to_numpy(), (d["fwd"] > 0).to_numpy().astype(int))
    spread = float(tabela["retorno_medio"].iloc[-1] - tabela["retorno_medio"].iloc[0])

    return Discriminacao(feature=feature, n=len(d), tabela=tabela, auc=auc, spread=spread)


def painel_features(painel: pd.DataFrame, p: Params) -> pd.DataFrame:
    """Aplica o motor de indicadores a cada papel e empilha tudo num só DataFrame."""
    from app.engine import indicators

    partes = []
    for tk, g in painel.groupby("ticker"):
        g = g.sort_values("timestamp").reset_index(drop=True)
        if len(g) < p.min_velas + 60:
            continue
        f = indicators.compute(g, p)
        f["ticker"] = tk
        partes.append(f)

    return pd.concat(partes, ignore_index=True) if partes else pd.DataFrame()
