"""Camada de aterrissagem do dado bruto: Parquet, um arquivo por (ativo, timeframe).

Por que Parquet e não Postgres direto:
  - o backtest (Fase 2) relê o histórico centenas de vezes durante o grid search;
    ler Parquet é ~instantâneo e não exige banco no ar;
  - o dado bruto é IMUTÁVEL — não há motivo para ele viver num banco transacional;
  - o Postgres (Fase 3) carrega A PARTIR daqui. Isto não é trabalho descartável.

Invariantes garantidas por este módulo (o resto do sistema depende delas):
  - `timestamp` é tz-aware em UTC, sempre;
  - não há timestamps duplicados;
  - as linhas estão ordenadas por timestamp crescente.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from app.core.config import DATA_DIR, Asset, Timeframe

COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]


def path_for(asset: Asset, tf: Timeframe) -> Path:
    return DATA_DIR / "ohlcv" / asset.market.value / asset.slug / f"{tf.value}.parquet"


def normalize(df: pd.DataFrame) -> pd.DataFrame:
    """Impõe as invariantes. Todo ingestor passa por aqui antes de gravar."""
    if df.empty:
        return pd.DataFrame(columns=COLUMNS).astype({"timestamp": "datetime64[ns, UTC]"})

    out = df.loc[:, COLUMNS].copy()
    ts = pd.to_datetime(out["timestamp"], utc=True)
    if ts.isna().any():
        raise ValueError("timestamp nulo ou não parseável no lote ingerido")
    out["timestamp"] = ts

    for c in ("open", "high", "low", "close", "volume"):
        out[c] = pd.to_numeric(out[c], errors="coerce")

    # Vela sem preço é lixo; vela sem volume é legítima (pregão parado).
    out = out.dropna(subset=["open", "high", "low", "close"])
    out["volume"] = out["volume"].fillna(0.0)

    return (
        out.drop_duplicates(subset="timestamp", keep="last")
        .sort_values("timestamp")
        .reset_index(drop=True)
    )


def read(asset: Asset, tf: Timeframe) -> pd.DataFrame:
    p = path_for(asset, tf)
    if not p.exists():
        return normalize(pd.DataFrame(columns=COLUMNS))
    return normalize(pd.read_parquet(p))


def upsert(asset: Asset, tf: Timeframe, novo: pd.DataFrame) -> int:
    """Funde o lote com o que já existe. Idempotente: reingerir o mesmo período é no-op.

    Retorna quantos timestamps NOVOS entraram (velas reescritas não contam).
    """
    novo = normalize(novo)
    if novo.empty:
        return 0

    atual = read(asset, tf)
    antes = set(atual["timestamp"])

    # `novo` por último → uma revisão da fonte sobrescreve a vela antiga.
    fundido = normalize(pd.concat([atual, novo], ignore_index=True))

    p = path_for(asset, tf)
    p.parent.mkdir(parents=True, exist_ok=True)
    fundido.to_parquet(p, index=False, compression="zstd")

    return len(set(fundido["timestamp"]) - antes)


def last_timestamp(asset: Asset, tf: Timeframe) -> pd.Timestamp | None:
    """Última vela armazenada — ponto de retomada do backfill incremental."""
    df = read(asset, tf)
    return None if df.empty else df["timestamp"].iloc[-1]


def purge(asset: Asset, tf: Timeframe) -> None:
    """Apaga a série. Necessário ao TROCAR de fonte.

    O Yahoo carimbava o pregão às 03:00 UTC; o COTAHIST, às 00:00. Fundir as duas fontes
    criaria DUAS velas por pregão — e o motor calcularia tudo sobre uma série com o dobro
    de linhas, silenciosamente errada.
    """
    p = path_for(asset, tf)
    p.unlink(missing_ok=True)


def span(asset: Asset, tf: Timeframe) -> tuple[pd.Timestamp, pd.Timestamp] | None:
    """(primeira, última) vela armazenada. None se a série não existe."""
    df = read(asset, tf)
    if df.empty:
        return None
    return df["timestamp"].iloc[0], df["timestamp"].iloc[-1]
