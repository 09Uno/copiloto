"""O sentimento carrega informação que o preço não tem?

Mesmo teste que reprovou o preço (AUC + calibração por decil, fora da amostra) — de propósito:
mudar a régua entre um candidato e outro é a forma mais fácil de aprovar o que se quer aprovar.

As features de texto, e o porquê de cada uma:

  tom            — o nível do sentimento no dia. A leitura ingênua da tese.
  tom_z          — o tom contra a PRÓPRIA história do papel. Uma empresa cronicamente mal
                   noticiada (a Americanas em 2023) tem tom sempre negativo; o que informa é o
                   desvio, não o nível.
  surpresa_tom   — variação do tom vs. a média recente. Notícia é choque, não estado.
  volume_z       — quantidade de artigos contra a própria média. Pico de cobertura = evento.
                   Tom sem volume é ruído de redação.
  tom_x_volume   — tom ponderado pela relevância. Sentimento ruim numa notícia que ninguém
                   leu não move preço.

**O alinhamento temporal é a armadilha aqui.** A notícia do dia D só pode ser usada para prever
o que acontece DEPOIS de D. Como o tom do dia D consolida artigos publicados ao longo daquele
dia — inclusive após o fechamento —, a entrada é na abertura de D+1. Usar o mesmo dia seria
lookahead: estaríamos "prevendo" um pregão que a notícia já descreveu.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

JANELA_Z = 60  # ~3 meses de pregão: referência do que é "normal" para aquele papel


def montar(precos: pd.DataFrame, tom: pd.DataFrame) -> pd.DataFrame:
    """Junta preço e sentimento por (ticker, dia) e deriva as features de texto."""
    if precos.empty or tom.empty:
        return pd.DataFrame()

    p = precos.copy()
    p["dia"] = pd.to_datetime(p["timestamp"], utc=True).dt.normalize()

    t = tom.copy()
    t["dia"] = pd.to_datetime(t["timestamp"], utc=True).dt.normalize()
    t["ticker_b3"] = t["ticker"].str.removesuffix(".SA")

    m = p.merge(
        t[["ticker_b3", "dia", "tom", "n_artigos"]],
        left_on=["ticker", "dia"],
        right_on=["ticker_b3", "dia"],
        how="inner",
    )
    if m.empty:
        return m

    m = m.sort_values(["ticker", "dia"]).reset_index(drop=True)
    g = m.groupby("ticker", sort=False)

    # Tom contra a PRÓPRIA história — o nível absoluto engana.
    mu = g["tom"].transform(lambda s: s.rolling(JANELA_Z, min_periods=20).mean())
    sd = g["tom"].transform(lambda s: s.rolling(JANELA_Z, min_periods=20).std())
    m["tom_z"] = np.where(sd > 0, (m["tom"] - mu) / sd, 0.0)
    m["surpresa_tom"] = m["tom"] - mu

    # Volume de cobertura contra a própria média. log1p: dias sem notícia existem.
    lv = np.log1p(m["n_artigos"].fillna(0))
    mv = lv.groupby(m["ticker"]).transform(lambda s: s.rolling(JANELA_Z, min_periods=20).mean())
    sv = lv.groupby(m["ticker"]).transform(lambda s: s.rolling(JANELA_Z, min_periods=20).std())
    m["volume_z"] = np.where(sv > 0, (lv - mv) / sv, 0.0)

    m["tom_x_volume"] = m["tom_z"] * m["volume_z"]

    return m


FEATURES = [
    ("tom", "tom bruto do dia"),
    ("tom_z", "tom vs. a própria história"),
    ("surpresa_tom", "surpresa (tom − média recente)"),
    ("volume_z", "pico de cobertura"),
    ("tom_x_volume", "tom ponderado por relevância"),
]
