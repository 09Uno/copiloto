"""Ingestor Binance — klines históricos (REST público, sem credencial).

É a fonte mais limpa e mais longa que existe de graça, e o único mercado com 15m
viável (SPEC §1). O backtest da Fase 2 se apoia principalmente neste dado.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime

import httpx
import pandas as pd

from app.core.config import Asset, Timeframe

BASE_URL = "https://api.binance.com/api/v3/klines"
MAX_LIMIT = 1000  # teto da API por página

# Colunas do array cru da Binance (as demais são ignoradas)
_OPEN_TIME, _OPEN, _HIGH, _LOW, _CLOSE, _VOLUME, _CLOSE_TIME = range(7)


def _fetch_page(
    client: httpx.Client, symbol: str, interval: str, start_ms: int, end_ms: int
) -> list[list]:
    """Uma página, com retry em rate limit (429) e erro transiente de servidor."""
    for tentativa in range(5):
        r = client.get(
            BASE_URL,
            params={
                "symbol": symbol,
                "interval": interval,
                "startTime": start_ms,
                "endTime": end_ms,
                "limit": MAX_LIMIT,
            },
            timeout=30.0,
        )
        if r.status_code == 200:
            return r.json()
        if r.status_code in (429, 418):  # rate limited / banido temporariamente
            espera = int(r.headers.get("Retry-After", 2 ** (tentativa + 1)))
            time.sleep(espera)
            continue
        if r.status_code >= 500:
            time.sleep(2**tentativa)
            continue
        r.raise_for_status()
    raise RuntimeError(f"Binance não respondeu para {symbol} {interval} após 5 tentativas")


def fetch_klines(
    asset: Asset, tf: Timeframe, inicio: datetime, fim: datetime | None = None
) -> pd.DataFrame:
    """Baixa [inicio, fim] paginando. Só retorna velas FECHADAS.

    A vela em formação tem OHLC que ainda vai mudar. Ingeri-la e calcular sinal em cima
    dela é lookahead disfarçado — o backtest fica ótimo e a produção não reproduz.
    """
    fim = fim or datetime.now(UTC)
    agora_ms = int(datetime.now(UTC).timestamp() * 1000)
    cursor = int(inicio.timestamp() * 1000)
    fim_ms = int(fim.timestamp() * 1000)

    linhas: list[list] = []
    with httpx.Client(headers={"User-Agent": "day-and-swing/0.1"}) as client:
        while cursor < fim_ms:
            page = _fetch_page(client, asset.ticker, tf.value, cursor, fim_ms)
            if not page:
                break

            # close_time no futuro ⇒ vela ainda aberta. Descarta.
            fechadas = [k for k in page if k[_CLOSE_TIME] < agora_ms]
            linhas.extend(fechadas)

            if len(page) < MAX_LIMIT:
                break
            cursor = page[-1][_OPEN_TIME] + 1  # +1ms evita rebaixar a última vela

    if not linhas:
        return pd.DataFrame()

    return pd.DataFrame(
        {
            "timestamp": pd.to_datetime([k[_OPEN_TIME] for k in linhas], unit="ms", utc=True),
            "open": [k[_OPEN] for k in linhas],
            "high": [k[_HIGH] for k in linhas],
            "low": [k[_LOW] for k in linhas],
            "close": [k[_CLOSE] for k in linhas],
            "volume": [k[_VOLUME] for k in linhas],
        }
    )
