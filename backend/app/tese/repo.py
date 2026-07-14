"""Persistência da tese (Supabase).

A tese é o único dado do sistema que **não é reprodutível**: preço, balanço e notícia dá para
rebaixar; o motivo pelo qual você comprou, não. É a sua memória — e é justamente o que o
cérebro reescreve depois que o preço se move.
"""

from __future__ import annotations

from dataclasses import dataclass

import asyncpg

from app.core import db
from app.tese.motor import Pilar


@dataclass
class Tese:
    id: int
    ticker: str
    classe: str
    resumo: str
    meta_yield: float | None
    preco_na_criacao: float | None
    pilares: list[Pilar]


async def criar(
    conn: asyncpg.Connection,
    ticker: str,
    classe: str,
    resumo: str,
    meta_yield: float,
    preco: float | None,
    pilares: list[Pilar],
    valores: dict[str, float | None],
) -> int:
    async with conn.transaction():
        tese_id = await conn.fetchval(
            """
            INSERT INTO teses (ticker, classe, resumo, meta_yield, preco_na_criacao)
                 VALUES ($1, $2, $3, $4, $5) RETURNING id
            """,
            ticker, classe, resumo, meta_yield, preco,
        )
        for p in pilares:
            await conn.execute(
                """
                INSERT INTO tese_pilares
                    (tese_id, metrica, operador, limite, valor_na_criacao,
                     qualitativo, descricao, prazo)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                """,
                tese_id, p.metrica, p.operador, p.limite,
                valores.get(p.metrica) if p.metrica else None,
                p.qualitativo, p.descricao, p.prazo,
            )
    return tese_id


async def ativas(conn: asyncpg.Connection, ticker: str | None = None) -> list[Tese]:
    linhas = await conn.fetch(
        """
        SELECT id, ticker, classe, resumo, meta_yield, preco_na_criacao
          FROM teses
         WHERE encerrada_em IS NULL AND ($1::text IS NULL OR ticker = $1)
         ORDER BY criada_em
        """,
        ticker,
    )

    out: list[Tese] = []
    for t in linhas:
        ps = await conn.fetch(
            """
            SELECT id, metrica, operador, limite, valor_na_criacao, qualitativo, descricao,
                   prazo
              FROM tese_pilares WHERE tese_id = $1 ORDER BY id
            """,
            t["id"],
        )
        out.append(
            Tese(
                id=t["id"], ticker=t["ticker"], classe=t["classe"], resumo=t["resumo"],
                meta_yield=float(t["meta_yield"]) if t["meta_yield"] else None,
                preco_na_criacao=(
                    float(t["preco_na_criacao"]) if t["preco_na_criacao"] else None
                ),
                pilares=[
                    Pilar(
                        id=p["id"], metrica=p["metrica"], operador=p["operador"],
                        limite=float(p["limite"]) if p["limite"] is not None else None,
                        valor_na_criacao=(
                            float(p["valor_na_criacao"])
                            if p["valor_na_criacao"] is not None else None
                        ),
                        qualitativo=p["qualitativo"], descricao=p["descricao"],
                        prazo=p["prazo"],
                    )
                    for p in ps
                ],
            )
        )
    return out


async def registrar_checagem(
    conn: asyncpg.Connection,
    tese_id: int,
    pilar_id: int,
    valor: float | None,
    passou: bool | None,
) -> None:
    """Guarda o histórico. É com ele que se responde, daqui a dois anos: *das minhas teses,
    quantas se confirmaram? eu acerto mais em elétrica ou em banco?*"""
    await conn.execute(
        """
        INSERT INTO tese_checagens (tese_id, pilar_id, valor, passou)
             VALUES ($1, $2, $3, $4)
        """,
        tese_id, pilar_id, valor, passou,
    )


async def encerrar(conn: asyncpg.Connection, tese_id: int, motivo: str) -> None:
    await conn.execute(
        "UPDATE teses SET encerrada_em = NOW(), motivo_encerramento = $2 WHERE id = $1",
        tese_id, motivo,
    )


async def conectar() -> asyncpg.Connection:
    return await db.connect()
