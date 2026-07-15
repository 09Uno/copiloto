"""Repositórios da API — acesso ao banco, isolado das rotas.

**Toda query de dado do usuário filtra por `user_id`.** É a guarda primária de isolamento
(a RLS-via-GUC entra depois, como defesa em profundidade, antes do primeiro usuário pago). Um
esquecimento aqui vazaria a carteira de um usuário para outro — por isso o `user_id` é sempre
o primeiro parâmetro, à vista.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import asyncpg

from app.api.pool import pool


# ---------------------------------------------------------------- usuários


@dataclass
class Usuario:
    id: uuid.UUID
    email: str
    senha_hash: str
    nome: str | None


async def criar_usuario(email: str, senha_hash: str, nome: str | None) -> Usuario:
    async with pool().acquire() as c:
        row = await c.fetchrow(
            """
            INSERT INTO users (email, senha_hash, nome) VALUES ($1, $2, $3)
            RETURNING id, email, senha_hash, nome
            """,
            email.lower().strip(), senha_hash, nome,
        )
        # Toda meta de yield vive por usuário — cria a linha de preferências junto.
        await c.execute(
            "INSERT INTO preferencias (user_id) VALUES ($1) ON CONFLICT DO NOTHING",
            row["id"],
        )
    return Usuario(row["id"], row["email"], row["senha_hash"], row["nome"])


async def buscar_por_email(email: str) -> Usuario | None:
    async with pool().acquire() as c:
        row = await c.fetchrow(
            "SELECT id, email, senha_hash, nome FROM users WHERE email = $1",
            email.lower().strip(),
        )
    return Usuario(row["id"], row["email"], row["senha_hash"], row["nome"]) if row else None


async def marcar_login(user_id: uuid.UUID) -> None:
    async with pool().acquire() as c:
        await c.execute("UPDATE users SET ultimo_login = NOW() WHERE id = $1", user_id)


# ---------------------------------------------------------------- preferências


async def meta_yield(user_id: uuid.UUID, classe: str) -> float:
    async with pool().acquire() as c:
        row = await c.fetchrow(
            "SELECT meta_yield_acao, meta_yield_fii FROM preferencias WHERE user_id = $1",
            user_id,
        )
    if not row:
        return 0.10 if classe == "FII" else 0.06
    return float(row["meta_yield_fii"] if classe == "FII" else row["meta_yield_acao"])


# ---------------------------------------------------------------- posições


@dataclass
class Posicao:
    ticker: str
    classe: str
    quantidade: float
    custo_medio: float
    fonte: str


async def posicoes(user_id: uuid.UUID) -> list[Posicao]:
    async with pool().acquire() as c:
        rows = await c.fetch(
            """
            SELECT ticker, classe, quantidade, custo_medio, fonte
              FROM posicoes WHERE user_id = $1 ORDER BY quantidade * custo_medio DESC
            """,
            user_id,
        )
    return [
        Posicao(r["ticker"], r["classe"], float(r["quantidade"]),
                float(r["custo_medio"]), r["fonte"])
        for r in rows
    ]


async def upsert_posicao(
    user_id: uuid.UUID, ticker: str, classe: str, qtd: float, custo: float, fonte: str
) -> None:
    async with pool().acquire() as c:
        await c.execute(
            """
            INSERT INTO posicoes (user_id, ticker, classe, quantidade, custo_medio, fonte)
                 VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (user_id, ticker) DO UPDATE
                    SET quantidade = EXCLUDED.quantidade,
                        custo_medio = EXCLUDED.custo_medio,
                        classe = EXCLUDED.classe,
                        fonte = EXCLUDED.fonte,
                        atualizada_em = NOW()
            """,
            user_id, ticker.upper().strip(), classe, qtd, custo, fonte,
        )


async def apagar_posicao(user_id: uuid.UUID, ticker: str) -> None:
    async with pool().acquire() as c:
        await c.execute(
            "DELETE FROM posicoes WHERE user_id = $1 AND ticker = $2",
            user_id, ticker.upper().strip(),
        )


async def substituir_posicoes_da_fonte(
    user_id: uuid.UUID, fonte: str, posicoes_novas: list[tuple]
) -> int:
    """Sincroniza uma fonte externa: apaga o que veio dela e regrava. Não toca no que é MANUAL.

    Numa transação — se a sincronização falhar no meio, a carteira não fica pela metade.
    """
    async with pool().acquire() as c, c.transaction():
        await c.execute(
            "DELETE FROM posicoes WHERE user_id = $1 AND fonte = $2", user_id, fonte
        )
        for ticker, classe, qtd, custo in posicoes_novas:
            await c.execute(
                """
                INSERT INTO posicoes (user_id, ticker, classe, quantidade, custo_medio, fonte)
                     VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (user_id, ticker) DO UPDATE
                        SET quantidade = EXCLUDED.quantidade,
                            custo_medio = EXCLUDED.custo_medio, fonte = EXCLUDED.fonte
                """,
                user_id, ticker, classe, qtd, custo, fonte,
            )
    return len(posicoes_novas)


# ---------------------------------------------------------------- fontes de carteira


async def salvar_fonte(user_id: uuid.UUID, tipo: str, config: dict) -> int:
    import json

    async with pool().acquire() as c:
        return await c.fetchval(
            """
            INSERT INTO carteira_fontes (user_id, tipo, config) VALUES ($1, $2, $3)
            RETURNING id
            """,
            user_id, tipo, json.dumps(config),
        )
