"""Ingestor EOD (yfinance) — ações B3 e EUA, diário.

`yfinance` não tem SLA e quebra sem aviso. Aqui isso é tratado como caso NORMAL:
falha devolve DataFrame vazio, o backfill segue para o próximo ativo e o gap é
detectado depois (`gaps.py`). Nada de exceção estourando no meio de um backfill de horas.

Só diário. Intraday do yfinance tem delay de 15min e cobertura ruim em B3 — não
sustenta reversão intradiária (SPEC §1).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
import yfinance as yf

from app.core.config import Asset, Timeframe


def fetch_daily(asset: Asset, inicio: datetime, fim: datetime | None = None) -> pd.DataFrame:
    fim = fim or datetime.now(UTC)

    try:
        raw = yf.Ticker(asset.ticker).history(
            start=inicio.date(),
            end=fim.date(),
            interval="1d",
            auto_adjust=False,  # preço bruto; ajuste é decisão do motor, não da fonte
            actions=False,
            raise_errors=True,
        )
    except Exception as exc:  # noqa: BLE001 — fonte instável por natureza
        print(f"  ! yfinance falhou para {asset.ticker}: {exc}")
        return pd.DataFrame()

    if raw.empty:
        return pd.DataFrame()

    df = raw.reset_index()
    ts_col = "Date" if "Date" in df.columns else "Datetime"

    # yfinance devolve o índice no fuso da bolsa; convertemos para UTC (invariante do store).
    ts = pd.to_datetime(df[ts_col])
    ts = ts.dt.tz_localize("UTC") if ts.dt.tz is None else ts.dt.tz_convert("UTC")

    return pd.DataFrame(
        {
            "timestamp": ts,
            "open": df["Open"],
            "high": df["High"],
            "low": df["Low"],
            "close": df["Close"],
            "volume": df["Volume"],
        }
    )


def fetch(asset: Asset, tf: Timeframe, inicio: datetime, fim: datetime | None = None):
    if tf is not Timeframe.D1:
        raise ValueError(
            f"{asset.ticker}: yfinance só é usado para EOD. "
            f"Timeframe {tf.value} não é viável em ação com dado gratuito (SPEC §1)."
        )
    return fetch_daily(asset, inicio, fim)
