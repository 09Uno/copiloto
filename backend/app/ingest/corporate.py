"""Ajuste por evento corporativo (desdobramento, grupamento, bonificação).

**Sem isto, o COTAHIST é inutilizável para o motor.** Ele traz o preço BRUTO negociado. Quando
o ITUB4 dá 10% de bonificação, o preço cai ~9% de um pregão para o outro sem que nada tenha
acontecido economicamente — e o motor leria isso como um desvio de vários σ, dispararia uma
compra falsa e ainda estouraria o ATR. Um desdobramento 1:2 seria um "-50%" fantasma.

O ajuste é RETROATIVO (o padrão do mercado): divide-se todo preço ANTERIOR ao evento pelo fator
acumulado dos eventos posteriores. Assim a série fica contínua e o retorno percentual, correto.

Volume: usamos o volume FINANCEIRO (R$), que é **invariante a desdobramento** — o dinheiro
negociado não muda porque o papel virou duas partes. Foi de propósito (cotahist.py lê VOLTOT).

Fonte dos eventos: yfinance. É um dataset minúsculo e estável, e mesmo para os tickers cujo
histórico de PREÇO o Yahoo se recusa a servir, os eventos costumam vir. Onde não vier, o salto
não explicado é DENUNCIADO (não silenciosamente aceito) — ver `jumps_nao_explicados`.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

from app.core.config import DATA_DIR

CACHE = DATA_DIR / "corporate"

# Um pregão que se move mais que isto sem evento corporativo conhecido é suspeito.
# Não é impossível (balanço desastroso acontece), mas merece o olho humano.
LIMIAR_SALTO = 0.25

# Reconciliação: só vale a pena caçar evento OMITIDO acima de 2% (em log). Abaixo disso é
# arredondamento de centavo — irrelevante para o motor e perigoso de "corrigir".
LIMIAR_EVENTO_OMITIDO = 0.02
JANELA_PLATO = 21  # ~1 mês de pregão: o patamar tem de se sustentar, não só piscar


def _cache_path(ticker: str) -> Path:
    return CACHE / f"{ticker.replace('.', '_')}.parquet"


def splits(ticker_yahoo: str, force: bool = False) -> pd.Series:
    """Fatores de desdobramento/bonificação por data (índice = data do evento, UTC)."""
    CACHE.mkdir(parents=True, exist_ok=True)
    p = _cache_path(ticker_yahoo)

    if p.exists() and not force:
        s = pd.read_parquet(p)
        if s.empty:
            return _vazio()
        return pd.Series(
            s["fator"].to_numpy(),
            index=pd.DatetimeIndex(s["data"]).tz_convert("UTC"),
            name="fator",
        )

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            raw = yf.Ticker(ticker_yahoo).splits
        except Exception:  # noqa: BLE001 — fonte instável; ausência de evento é o caso comum
            raw = None

    # Ticker que o Yahoo não conhece devolve None (não uma série vazia). Sem evento conhecido
    # o ajuste é neutro — e o alarme de `jumps_nao_explicados` passa a ser a única defesa.
    if raw is None or len(raw) == 0:
        out = _vazio()
    else:
        idx = pd.DatetimeIndex(raw.index).tz_convert("UTC")
        out = pd.Series(raw.to_numpy(dtype=float), index=idx, name="fator")

    pd.DataFrame({"data": out.index, "fator": out.to_numpy()}).to_parquet(p, index=False)
    return out


def _vazio() -> pd.Series:
    return pd.Series(
        [], index=pd.DatetimeIndex([], tz="UTC"), name="fator", dtype=float
    )


def adjust(df: pd.DataFrame, eventos: pd.Series) -> pd.DataFrame:
    """Aplica o ajuste retroativo ao OHLC. Volume financeiro fica intacto (é invariante).

    Para cada vela, o fator é o PRODUTO dos eventos que ocorreram DEPOIS dela.
    Preço ajustado = preço bruto / fator.
    """
    if df.empty or eventos.empty:
        return df

    out = df.copy()
    ts = pd.to_datetime(out["timestamp"], utc=True)

    # fator_acumulado[i] = produto dos eventos com data > ts[i]
    fator = np.ones(len(out))
    for data_evento, f in eventos.items():
        if not f or f <= 0:
            continue

        # NORMALIZAR a data do evento é OBRIGATÓRIO. O Yahoo carimba o split com hora
        # (10:00 de Brasília = 13:00 UTC); o pregão do COTAHIST é 00:00 UTC. Sem normalizar,
        # `ts < data_evento` inclui o PRÓPRIO DIA EX — que já negocia no preço pós-split — e
        # o divide de novo. O resultado é um salto fantasma de +100% em toda data de
        # desdobramento, justamente onde a série tinha de ficar contínua.
        ex = pd.Timestamp(data_evento).tz_convert("UTC").normalize()
        fator *= np.where(ts < ex, f, 1.0)

    for c in ("open", "high", "low", "close"):
        out[c] = out[c] / fator

    return out


def reconcile(df_ajustado: pd.DataFrame, ref_close: pd.Series) -> pd.Series:
    """Descobre eventos que a lista do Yahoo OMITE, comparando com a série de preços dele.

    A lista de splits do Yahoo é **inconsistente com o próprio preço do Yahoo**. No MGLU3, a
    razão entre a nossa série ajustada e a dele é exatamente 1,0691 de 2011 a 2023 e cai para
    1,000 em 2024: existe um evento de ~6,9% em 2024 que ele aplica no preço mas não declara.
    Um buraco desses não dispara o alarme de 25%, mas é um falso movimento de 1-2σ — e sinal
    fantasma é pior que nenhum sinal.

    A assinatura de um evento omitido é inconfundível: um DEGRAU limpo na razão entre as duas
    séries. Ruído de arredondamento oscila; evento corporativo dá um salto e fica lá.

    `ref_close` = fechamento de referência (Yahoo), indexado por data. Devolve os eventos
    faltantes, para somar aos conhecidos.
    """
    if df_ajustado.empty or ref_close.empty:
        return _vazio()

    d = df_ajustado.copy()
    d["_d"] = pd.to_datetime(d["timestamp"], utc=True).dt.normalize()

    ref = ref_close.rename("ref").to_frame()
    ref.index = pd.DatetimeIndex(ref.index).tz_convert("UTC").normalize()

    m = d.set_index("_d").join(ref, how="inner").sort_index()
    if len(m) < 2 * JANELA_PLATO:
        return _vazio()

    log_r = np.log(m["close"] / m["ref"]).to_numpy()

    # Comparar PATAMARES, não velas vizinhas. Um evento omitido move a razão para um novo
    # nível e ela FICA lá; ruído de arredondamento treme e volta. Numa ação de R$ 1,00 um
    # centavo já é 1% — comparar dia a dia detectaria "evento" o tempo todo, e compor esses
    # fatores espúrios destrói a série (foi o que aconteceu: 10.867 falsos eventos).
    antes = pd.Series(log_r).rolling(JANELA_PLATO).median().to_numpy()
    depois = pd.Series(log_r[::-1]).rolling(JANELA_PLATO).median().to_numpy()[::-1]
    passo_diario = np.abs(np.diff(log_r, prepend=log_r[0]))

    datas, fatores, ultimo = [], [], -JANELA_PLATO
    for i in range(JANELA_PLATO, len(log_r) - JANELA_PLATO):
        if np.isnan(antes[i - 1]) or np.isnan(depois[i]):
            continue

        salto = antes[i - 1] - depois[i]
        if abs(salto) <= LIMIAR_EVENTO_OMITIDO:
            continue
        if i - ultimo < JANELA_PLATO:  # o mesmo degrau, visto de vários ângulos
            continue

        # A MEDIANA vira assim que a maioria da janela já é pós-evento — ou seja, ela acusa
        # o degrau até ~meia janela cedo demais. Ela é ótima para MEDIR o salto (é robusta) e
        # péssima para DATÁ-LO. A data exata é o dia em que a razão de fato deu o pulo.
        ini = max(1, i - JANELA_PLATO)
        fim = min(len(log_r), i + JANELA_PLATO)
        exato = ini + int(np.argmax(passo_diario[ini:fim]))

        datas.append(m.index[exato])
        fatores.append(float(np.exp(salto)))
        ultimo = i

    if not datas:
        return _vazio()
    return pd.Series(fatores, index=pd.DatetimeIndex(datas, tz="UTC"), name="fator")


def jumps_nao_explicados(df: pd.DataFrame, eventos: pd.Series) -> pd.DataFrame:
    """Saltos que o ajuste NÃO explica. É o alarme contra evento corporativo desconhecido.

    Aceitar um salto desses em silêncio significa deixar o motor tratar um grupamento como
    um crash de 50% — e o backtest reporta uma borda que nunca existiu.
    """
    if len(df) < 2:
        return df.iloc[:0]

    r = np.log(df["close"] / df["close"].shift(1))
    suspeito = r.abs() > LIMIAR_SALTO

    if eventos is not None and len(eventos):
        datas = pd.DatetimeIndex(eventos.index).normalize()
        no_evento = pd.to_datetime(df["timestamp"], utc=True).dt.normalize().isin(datas)
        suspeito &= ~no_evento

    out = df.loc[suspeito, ["timestamp", "close"]].copy()
    out["variacao_pct"] = (np.exp(r[suspeito]) - 1) * 100
    return out
