"""Rotas da tese — o núcleo do produto.

A tela de criação é a que **recusa "vai subir"**: um pilar tem de ser verificável. E o motor
não sabe o que é "payout" — ele pergunta à classe do ativo. A API só traduz HTTP ↔ motor.

O sistema NUNCA diz "venda". A checagem devolve a decisão ao usuário:
*"Você comprou por N motivos. Caíram X. Você compraria hoje?"*
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.api import avaliador, repo
from app.api.deps import usuario_atual
from app.api.pool import pool
from app.ativos import base as ab
from app.tese import motor as tm

router = APIRouter(prefix="/api/teses", tags=["teses"])


class PilarIn(BaseModel):
    texto: str | None = None          # "payout<80%" ou "divida_ebit<5.0@2028-06"
    qualitativo: str | None = None    # "monopólio regulado"


class TeseIn(BaseModel):
    ticker: str
    resumo: str
    pilares: list[PilarIn]
    aceitar_quebrado: str | None = None  # motivo, se comprar mesmo com pilar já violado


class ResultadoOut(BaseModel):
    pilar: str
    estado: str
    valor: float | None
    motivo: str | None


class VeredictoOut(BaseModel):
    tese_id: int
    ticker: str
    resumo: str
    resultados: list[ResultadoOut]
    de_pe: int
    total_verificaveis: int
    pergunta: str


def _out(tese_id: int, v: tm.Veredito) -> VeredictoOut:
    return VeredictoOut(
        tese_id=tese_id, ticker=v.ticker, resumo=v.resumo,
        resultados=[
            ResultadoOut(pilar=str(r.pilar), estado=r.estado.value, valor=r.valor,
                         motivo=r.motivo)
            for r in v.resultados
        ],
        de_pe=v.de_pe, total_verificaveis=v.total_verificaveis, pergunta=v.pergunta,
    )


@router.post("", response_model=VeredictoOut, status_code=201)
async def criar(dados: TeseIn, user_id: uuid.UUID = Depends(usuario_atual)) -> VeredictoOut:
    tk = dados.ticker.upper().strip()
    classe = ab.classificar(tk)
    meta = await repo.meta_yield(user_id, classe.value)
    av = avaliador.avaliar(tk, meta)

    impl = ab.para(classe)
    disponiveis = impl.metricas_disponiveis() if impl else {}

    # --- traduz os pilares, RECUSANDO os que não dão para checar
    pilares: list[tm.Pilar] = []
    for p in dados.pilares:
        if p.qualitativo:
            pilares.append(tm.Pilar(id=None, metrica=None, operador=None, limite=None,
                                    qualitativo=True, descricao=p.qualitativo))
        elif p.texto:
            try:
                pilares.append(tm.parse_pilar(p.texto, disponiveis))
            except ValueError as e:
                # 422 com a mensagem que ENSINA o que existe — "vai subir" cai aqui.
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e)) from None

    if not pilares:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "uma tese sem pilares não é uma tese")

    # --- guarda-corpo: tese que já nasce quebrada
    v0 = tm.verificar(av, dados.resumo, pilares)
    if v0.cairam and not dados.aceitar_quebrado:
        quebrados = "; ".join(f"{r.pilar} (hoje {r.valor:g})" for r in v0.cairam)
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Esta tese já nasce quebrada: {quebrados}. "
            "Ajuste o limite, declare como aposta (metrica<valor@AAAA-MM), ou confirme com "
            "'aceitar_quebrado' explicando o porquê.",
        )

    resumo = dados.resumo
    if dados.aceitar_quebrado:
        resumo += f"  [pilar quebrado aceito: {dados.aceitar_quebrado}]"

    # --- persiste
    async with pool().acquire() as c, c.transaction():
        tese_id = await c.fetchval(
            """
            INSERT INTO teses (user_id, ticker, classe, resumo, meta_yield, preco_na_criacao)
                 VALUES ($1, $2, $3, $4, $5, $6) RETURNING id
            """,
            user_id, tk, classe.value, resumo, meta, av.preco,
        )
        for p in pilares:
            await c.execute(
                """
                INSERT INTO tese_pilares
                    (tese_id, metrica, operador, limite, valor_na_criacao, qualitativo,
                     descricao, prazo)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                """,
                tese_id, p.metrica, p.operador, p.limite,
                av.metrica(p.metrica) if p.metrica else None,
                p.qualitativo, p.descricao, p.prazo,
            )

    return _out(tese_id, tm.verificar(av, resumo, pilares))


@router.get("", response_model=list[VeredictoOut])
async def checar_todas(user_id: uuid.UUID = Depends(usuario_atual)) -> list[VeredictoOut]:
    """Checa todas as teses ativas do usuário contra os fundamentos de hoje."""
    async with pool().acquire() as c:
        teses = await c.fetch(
            """
            SELECT id, ticker, classe, resumo, meta_yield, preco_na_criacao
              FROM teses WHERE user_id = $1 AND encerrada_em IS NULL ORDER BY criada_em
            """,
            user_id,
        )

        saida = []
        for t in teses:
            ps = await c.fetch(
                """
                SELECT id, metrica, operador, limite, valor_na_criacao, qualitativo,
                       descricao, prazo
                  FROM tese_pilares WHERE tese_id = $1 ORDER BY id
                """,
                t["id"],
            )
            pilares = [
                tm.Pilar(
                    id=p["id"], metrica=p["metrica"], operador=p["operador"],
                    limite=float(p["limite"]) if p["limite"] is not None else None,
                    valor_na_criacao=(float(p["valor_na_criacao"])
                                      if p["valor_na_criacao"] is not None else None),
                    qualitativo=p["qualitativo"], descricao=p["descricao"], prazo=p["prazo"],
                )
                for p in ps
            ]
            meta = float(t["meta_yield"]) if t["meta_yield"] else 0.06
            av = avaliador.avaliar(t["ticker"], meta)
            saida.append(_out(t["id"], tm.verificar(av, t["resumo"], pilares)))
    return saida


@router.delete("/{tese_id}", status_code=204)
async def encerrar(
    tese_id: int, motivo: str, user_id: uuid.UUID = Depends(usuario_atual)
) -> None:
    async with pool().acquire() as c:
        # O AND user_id garante que ninguém encerra a tese de outro.
        r = await c.execute(
            """
            UPDATE teses SET encerrada_em = NOW(), motivo_encerramento = $3
             WHERE id = $1 AND user_id = $2 AND encerrada_em IS NULL
            """,
            tese_id, user_id, motivo,
        )
    if r.endswith("0"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "tese não encontrada")
