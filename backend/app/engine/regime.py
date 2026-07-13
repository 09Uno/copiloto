"""Classificação de regime (SPEC §2.5). Módulo puro.

É a peça que faltava no plano original, e a que evita o erro mais caro da reversão à média:
**comprar o rompimento de −2σ dentro de uma tendência de baixa forte.** Ali a banda não é
exaustão, é continuação — e comprar é pegar faca caindo.

O R² é o juiz. Ele não mede a INCLINAÇÃO da tendência, mede o quanto o preço de fato ADERE
a ela. R² alto = movimento organizado, direcional, que não deve ser contrariado. R² baixo =
o preço vai e volta em torno da média, que é exatamente a premissa da reversão.
"""

from __future__ import annotations

from enum import StrEnum

import numpy as np
import pandas as pd

from app.core.config import Params


class MarketRegime(StrEnum):
    LATERAL = "LATERAL"      # único regime onde a reversão à média é operada
    TENDENCIA = "TENDENCIA"  # a banda vira continuação; o motor não opera contra
    NERVOSO = "NERVOSO"      # choque de volatilidade: o ATR explodiu vs. sua própria mediana


def classify(df: pd.DataFrame, p: Params) -> pd.Series:
    """Exige as colunas de `indicators.compute`. NaN nas features → regime NaN."""
    r2 = df["regression_r2"]
    atr_pct = df["atr_pct"]
    mediana = df["atr_pct_mediana"]

    # NERVOSO tem precedência: num choque de volatilidade, o R² baixo é ruído, não lateralidade.
    # O ATR é comparado com a MEDIANA DELE MESMO — não com um limiar absoluto, que seria
    # incomparável entre BTC e ITUB4.
    nervoso = atr_pct > (p.regime.nervoso_atr_mult * mediana)
    tendencia = r2 >= p.regime.r2_max_lateral

    regime = pd.Series(
        np.select(
            [nervoso, tendencia],
            [MarketRegime.NERVOSO.value, MarketRegime.TENDENCIA.value],
            default=MarketRegime.LATERAL.value,
        ),
        index=df.index,
        name="market_regime",
        dtype=object,
    )

    incompleto = r2.isna() | atr_pct.isna() | mediana.isna()
    regime[incompleto] = None
    return regime
