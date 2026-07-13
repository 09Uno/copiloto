"""Conexão com o Postgres (Supabase) e carga do Parquet.

O Parquet continua sendo a fonte da verdade do dado bruto: ele é imutável, reprodutível
e o backtest (Fase 2) lê dele direto, sem banco no ar. O Postgres é a camada de SERVIÇO —
é dele que a API (Fase 3) e o dashboard leem. `db load` sincroniza um a partir do outro.
"""

from __future__ import annotations

import os
from decimal import Decimal

import asyncpg

from app.core.config import BACKEND_DIR, PROJECT_DIR, Asset, Timeframe, watchlist
from app.ingest import store

SCHEMA_PATH = PROJECT_DIR / "infra" / "schema.sql"


def database_url() -> str:
    """Lê do ambiente, com fallback para backend/.env (que nunca é versionado)."""
    if url := os.getenv("DATABASE_URL"):
        return url

    env = BACKEND_DIR / ".env"
    if env.exists():
        for linha in env.read_text(encoding="utf-8").splitlines():
            linha = linha.strip()
            if linha.startswith("DATABASE_URL="):
                return linha.split("=", 1)[1].strip()

    raise RuntimeError("DATABASE_URL não definida. Copie backend/.env.example para .env.")


async def connect() -> asyncpg.Connection:
    # statement_cache_size=0: o pooler do Supabase (pgbouncer) não suporta prepared
    # statements nomeados. Sem isso, a segunda query da sessão estoura.
    return await asyncpg.connect(database_url(), statement_cache_size=0)


async def init_schema() -> None:
    conn = await connect()
    try:
        await conn.execute(SCHEMA_PATH.read_text(encoding="utf-8"))
    finally:
        await conn.close()


async def sync_assets(conn: asyncpg.Connection) -> dict[str, int]:
    """Espelha a watchlist do config no banco. Devolve ticker → asset_id."""
    for a in watchlist():
        await conn.execute(
            """
            INSERT INTO assets (ticker, market_type, name, is_watchlist, timeframes, currency)
                 VALUES ($1, $2, $3, TRUE, $4, $5)
            ON CONFLICT (ticker, market_type) DO UPDATE
                    SET name = EXCLUDED.name,
                        is_watchlist = EXCLUDED.is_watchlist,
                        timeframes = EXCLUDED.timeframes,
                        currency = EXCLUDED.currency
            """,
            a.ticker,
            a.market.value,
            a.name,
            [tf.value for tf in a.timeframes],
            a.currency,
        )

    linhas = await conn.fetch("SELECT id, ticker FROM assets")
    return {r["ticker"]: r["id"] for r in linhas}


async def upsert_account(
    conn: asyncpg.Connection, currency: str, saldo: Decimal, risco_pct: Decimal
) -> None:
    """Cria/atualiza uma banca. Uma por moeda (SPEC §8.1).

    `cash_balance` só é inicializado na criação — reaplicar o comando não zera o caixa
    de uma conta que já está operando.
    """
    await conn.execute(
        """
        INSERT INTO accounts (name, currency, initial_balance, cash_balance, risk_per_trade_pct)
             VALUES ($1, $2, $3, $3, $4)
        ON CONFLICT (currency) DO UPDATE
                SET initial_balance = EXCLUDED.initial_balance,
                    risk_per_trade_pct = EXCLUDED.risk_per_trade_pct
        """,
        f"Banca {currency}",
        currency,
        saldo,
        risco_pct,
    )


async def load_series(conn: asyncpg.Connection, asset: Asset, tf: Timeframe, asset_id: int) -> int:
    """Carrega uma série do Parquet para o Postgres. Idempotente.

    Vai para uma tabela temporária e daí faz INSERT ... ON CONFLICT: dá a velocidade do
    COPY sem quebrar quando a vela já existe (recarregar é operação rotineira).
    """
    df = store.read(asset, tf)
    if df.empty:
        return 0

    # NUMERIC do Postgres exige Decimal — float estoura no COPY. Via str para não
    # arrastar o erro binário do float64 para dentro do preço.
    registros = [
        (
            asset_id,
            tf.value,
            r.timestamp.to_pydatetime(),
            Decimal(str(r.open)),
            Decimal(str(r.high)),
            Decimal(str(r.low)),
            Decimal(str(r.close)),
            Decimal(str(r.volume)),
        )
        for r in df.itertuples()
    ]

    async with conn.transaction():
        await conn.execute(
            "CREATE TEMP TABLE tmp_prices "
            "(LIKE asset_prices INCLUDING DEFAULTS) ON COMMIT DROP"
        )
        await conn.copy_records_to_table("tmp_prices", records=registros)
        await conn.execute(
            """
            INSERT INTO asset_prices
            SELECT * FROM tmp_prices
            ON CONFLICT (asset_id, timeframe, timestamp) DO UPDATE
                SET open_price  = EXCLUDED.open_price,
                    high_price  = EXCLUDED.high_price,
                    low_price   = EXCLUDED.low_price,
                    close_price = EXCLUDED.close_price,
                    volume      = EXCLUDED.volume
            """
        )
    return len(registros)
