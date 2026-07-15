"""Pool de conexões da API.

Uma conexão por request seria lento e estouraria o limite do pooler do Supabase. O pool vive
enquanto a API vive.

`statement_cache_size=0` de novo: o pooler do Supabase (pgbouncer) não suporta prepared
statements nomeados. Na VPS com Postgres direto isso não faria falta, mas também não atrapalha
— manter portável.
"""

from __future__ import annotations

import asyncpg

from app.core import db

_pool: asyncpg.Pool | None = None


async def abrir() -> None:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            db.database_url(),
            min_size=1,
            max_size=8,
            statement_cache_size=0,
        )


async def fechar() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("pool não inicializado — chame abrir() no startup da API")
    return _pool
