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


async def margem_seguranca(user_id: uuid.UUID) -> float:
    """O desconto abaixo do teto que define a zona de compra. Default 15% se não houver linha."""
    async with pool().acquire() as c:
        v = await c.fetchval(
            "SELECT margem_seguranca FROM preferencias WHERE user_id = $1", user_id
        )
    return float(v) if v is not None else 0.15


@dataclass
class Preferencias:
    meta_yield_acao: float
    meta_yield_fii: float
    margem_seguranca: float
    email_alertas: bool


async def preferencias(user_id: uuid.UUID) -> Preferencias:
    """Todas as preferências do usuário de uma vez — o que a tela de ajustes edita.

    Se a linha não existir (usuário antigo), devolve os mesmos defaults do schema, para a tela
    nunca abrir vazia.
    """
    async with pool().acquire() as c:
        row = await c.fetchrow(
            """
            SELECT meta_yield_acao, meta_yield_fii, margem_seguranca, email_alertas
              FROM preferencias WHERE user_id = $1
            """,
            user_id,
        )
    if not row:
        return Preferencias(0.06, 0.10, 0.15, True)
    return Preferencias(
        float(row["meta_yield_acao"]), float(row["meta_yield_fii"]),
        float(row["margem_seguranca"]), bool(row["email_alertas"]),
    )


async def atualizar_preferencias(
    user_id: uuid.UUID,
    meta_yield_acao: float,
    meta_yield_fii: float,
    margem_seguranca: float,
    email_alertas: bool,
) -> Preferencias:
    """Grava as preferências. Faz upsert: um usuário sem linha ainda é ajustável."""
    async with pool().acquire() as c:
        row = await c.fetchrow(
            """
            INSERT INTO preferencias
                (user_id, meta_yield_acao, meta_yield_fii, margem_seguranca, email_alertas)
                 VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (user_id) DO UPDATE
                    SET meta_yield_acao = EXCLUDED.meta_yield_acao,
                        meta_yield_fii = EXCLUDED.meta_yield_fii,
                        margem_seguranca = EXCLUDED.margem_seguranca,
                        email_alertas = EXCLUDED.email_alertas
              RETURNING meta_yield_acao, meta_yield_fii, margem_seguranca, email_alertas
            """,
            user_id, meta_yield_acao, meta_yield_fii, margem_seguranca, email_alertas,
        )
    return Preferencias(
        float(row["meta_yield_acao"]), float(row["meta_yield_fii"]),
        float(row["margem_seguranca"]), bool(row["email_alertas"]),
    )


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


async def tickers_carteira(user_id: uuid.UUID) -> set[str]:
    """Só os tickers que o usuário TEM — para separar 'na carteira' de 'de olho' (watchlist)."""
    async with pool().acquire() as c:
        rows = await c.fetch("SELECT ticker FROM posicoes WHERE user_id = $1", user_id)
    return {r["ticker"] for r in rows}


async def tickers_acompanhados(user_id: uuid.UUID) -> list[tuple[str, bool]]:
    """Tudo que o usuário acompanha, para o feed: carteira ∪ teses ativas.

    Devolve (ticker, na_carteira) — a carteira ganha, então um ticker que está na carteira E tem
    tese aparece como na_carteira=True (não como watchlist). Ordenado para o feed sair estável.
    """
    async with pool().acquire() as c:
        pos = await c.fetch("SELECT ticker FROM posicoes WHERE user_id = $1", user_id)
        tes = await c.fetch(
            "SELECT DISTINCT ticker FROM teses WHERE user_id = $1 AND encerrada_em IS NULL",
            user_id,
        )
    carteira = {r["ticker"] for r in pos}
    todos = carteira | {r["ticker"] for r in tes}
    return sorted((t, t in carteira) for t in todos)


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


# ---------------------------------------------------------------- contexto do pilar


@dataclass
class PilarDono:
    id: int
    ticker: str
    descricao: str | None
    qualitativo: bool


async def pilar_do_usuario(user_id: uuid.UUID, pilar_id: int) -> PilarDono | None:
    """O pilar, SÓ se pertencer a uma tese ativa deste usuário. O JOIN é a guarda de dono —
    ninguém busca contexto do pilar de outro."""
    async with pool().acquire() as c:
        r = await c.fetchrow(
            """
            SELECT tp.id, t.ticker, tp.descricao, tp.qualitativo
              FROM tese_pilares tp JOIN teses t ON t.id = tp.tese_id
             WHERE tp.id = $1 AND t.user_id = $2 AND t.encerrada_em IS NULL
            """,
            pilar_id, user_id,
        )
    return PilarDono(r["id"], r["ticker"], r["descricao"], r["qualitativo"]) if r else None


def _contexto_dict(r) -> dict:
    import json

    achados = r["achados"]
    return {
        "buscado_em": r["buscado_em"].isoformat(),
        "nada_mudou": r["nada_mudou"],
        "achados": json.loads(achados) if isinstance(achados, str) else achados,
    }


async def ultimo_contexto(pilar_id: int) -> dict | None:
    async with pool().acquire() as c:
        r = await c.fetchrow(
            "SELECT buscado_em, nada_mudou, achados FROM contexto_pilar WHERE pilar_id = $1",
            pilar_id,
        )
    return _contexto_dict(r) if r else None


async def salvar_contexto(pilar_id: int, nada_mudou: bool, achados: list[dict]) -> None:
    import json

    async with pool().acquire() as c:
        await c.execute(
            """
            INSERT INTO contexto_pilar (pilar_id, buscado_em, nada_mudou, achados)
                 VALUES ($1, NOW(), $2, $3)
            ON CONFLICT (pilar_id) DO UPDATE
                    SET buscado_em = NOW(),
                        nada_mudou = EXCLUDED.nada_mudou,
                        achados = EXCLUDED.achados
            """,
            pilar_id, nada_mudou, json.dumps(achados),
        )


async def contextos_do_usuario(user_id: uuid.UUID) -> dict[int, dict]:
    """A última busca de cada pilar das teses ativas — para o painel mostrar sem N requisições."""
    async with pool().acquire() as c:
        rows = await c.fetch(
            """
            SELECT cp.pilar_id, cp.buscado_em, cp.nada_mudou, cp.achados
              FROM contexto_pilar cp
              JOIN tese_pilares tp ON tp.id = cp.pilar_id
              JOIN teses t ON t.id = tp.tese_id
             WHERE t.user_id = $1 AND t.encerrada_em IS NULL
            """,
            user_id,
        )
    return {r["pilar_id"]: _contexto_dict(r) for r in rows}
