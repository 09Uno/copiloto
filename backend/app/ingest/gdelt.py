"""GDELT — tom diário da imprensa por empresa (a única fonte com HISTÓRICO grátis).

É a última hipótese não testada, e é a original do projeto: **o texto carrega informação que o
preço não tem.** O preço já foi reprovado — AUC ~0,50 fora da amostra, em 936 mil observações.

Por que GDELT e não Reddit/fóruns: para MEDIR se o sentimento informa, é preciso sentimento
HISTÓRICO alinhado com preço. O Pushshift (arquivo do Reddit) morreu, fóruns brasileiros não
têm arquivo público e RSS não guarda passado. Sem histórico, só daria para começar a coletar
hoje e descobrir daqui a um ano. O GDELT tem tom diário desde 2017, de graça.

Duas séries por empresa, e as duas importam:
  · TOM     — média do sentimento dos artigos do dia (negativo = ruim)
  · VOLUME  — quantos artigos. Um pico de volume é notícia relevante; tom sem volume é ruído.
"""

from __future__ import annotations

import time

import httpx
import pandas as pd

from app.core.config import DATA_DIR
from app.core.gdelt_map import consulta

BASE = "https://api.gdeltproject.org/api/v2/doc/doc"
CACHE = DATA_DIR / "gdelt"

# O GDELT ANUNCIA 5s entre requisições, mas na prática só aceita uma a cada ~25s: medindo,
# passava 1 em cada 3 tentativas espaçadas de 8s. Espaçar de menos não acelera nada — só
# gera 429 e faz o coletor desistir achando que a empresa não tem cobertura (foi o que
# aconteceu com a PETROBRAS, que tem 13 mil artigos por ano).
INTERVALO = 25.0
MAX_TENTATIVAS = 8

_ultima_chamada = 0.0


def _throttle() -> None:
    """Espaçamento GLOBAL entre requisições — não por tentativa."""
    global _ultima_chamada
    espera = INTERVALO - (time.monotonic() - _ultima_chamada)
    if espera > 0:
        time.sleep(espera)
    _ultima_chamada = time.monotonic()


def _get(query: str, ini: str, fim: str, mode: str) -> list[dict]:
    for tentativa in range(MAX_TENTATIVAS):
        _throttle()
        try:
            r = httpx.get(
                BASE,
                params={
                    "query": query, "mode": mode,
                    "startdatetime": ini, "enddatetime": fim, "format": "json",
                },
                timeout=180.0,
                headers={"User-Agent": "day-and-swing/0.1"},
            )
        except httpx.RequestError:
            continue

        if r.status_code == 429:
            time.sleep(10 * (tentativa + 1))  # penalidade extra: o servidor pediu calma
            continue
        if r.status_code != 200:
            return []

        try:
            j = r.json()
        except ValueError:
            return []

        linha = j.get("timeline") or []
        return linha[0].get("data", []) if linha else []

    return []


def fetch(ticker: str, ano_ini: int, ano_fim: int, force: bool = False) -> pd.DataFrame:
    """Série diária de (tom, volume) para um papel. Cache por ticker — o passado não muda."""
    q = consulta(ticker)
    if q is None:
        return pd.DataFrame()

    CACHE.mkdir(parents=True, exist_ok=True)
    p = CACHE / f"{ticker.replace('.', '_')}.parquet"
    if p.exists() and not force:
        return pd.read_parquet(p)

    ini = f"{ano_ini}0101000000"
    fim = f"{ano_fim}1231000000"

    tom = _get(q, ini, fim, "timelinetone")
    vol = _get(q, ini, fim, "timelinevolraw")
    if not tom:
        return pd.DataFrame()

    df = pd.DataFrame(
        {
            "timestamp": pd.to_datetime([x["date"] for x in tom], utc=True).normalize(),
            "tom": [float(x["value"]) for x in tom],
        }
    )

    if vol:
        v = pd.DataFrame(
            {
                "timestamp": pd.to_datetime([x["date"] for x in vol], utc=True).normalize(),
                "n_artigos": [float(x["value"]) for x in vol],
            }
        )
        df = df.merge(v, on="timestamp", how="left")
    else:
        df["n_artigos"] = float("nan")

    df["ticker"] = ticker
    df = df.drop_duplicates("timestamp").sort_values("timestamp").reset_index(drop=True)
    df.to_parquet(p, index=False, compression="zstd")
    return df


def load_todos() -> pd.DataFrame:
    if not CACHE.exists():
        return pd.DataFrame()
    partes = [pd.read_parquet(f) for f in sorted(CACHE.glob("*.parquet"))]
    return pd.concat(partes, ignore_index=True) if partes else pd.DataFrame()
