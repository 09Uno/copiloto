"""Rota do contexto — a "versão honesta" da checagem de pilar qualitativo.

Você clica em "buscar o que mudou" num pilar que só você julga ("monopólio regulado"). O sistema
lê as notícias, o LLM FILTRA as que tocam aquela afirmação (nunca dá veredito) e devolve citadas.
A decisão continua sua. Manual de propósito: cada clique custa token, e a busca é sob demanda.
"""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.api import repo
from app.api.deps import usuario_atual
from app.contexto import buscador

router = APIRouter(prefix="/api/contexto", tags=["contexto"])


class AchadoOut(BaseModel):
    resumo: str
    url: str
    fonte: str
    data: str | None
    relevancia: str


class ContextoOut(BaseModel):
    buscado_em: str
    nada_mudou: bool
    achados: list[AchadoOut]


@router.get("/disponivel")
async def disponivel(_: uuid.UUID = Depends(usuario_atual)) -> dict:
    """A tela pergunta antes de mostrar o botão — sem chave, ele nem aparece."""
    return {"disponivel": buscador.disponivel()}


@router.post("/pilar/{pilar_id}", response_model=ContextoOut)
async def buscar_contexto(
    pilar_id: int, user_id: uuid.UUID = Depends(usuario_atual)
) -> ContextoOut:
    # O JOIN por user_id é a guarda de dono — ninguém busca contexto do pilar de outro.
    dono = await repo.pilar_do_usuario(user_id, pilar_id)
    if dono is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "pilar não encontrado")
    if not dono.qualitativo or not (dono.descricao or "").strip():
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "só pilares qualitativos têm contexto a buscar — os de número o sistema já confere.",
        )

    # A última busca vira o "desde quando": a próxima traz só o que mudou.
    anterior = await repo.ultimo_contexto(pilar_id)
    desde = date.fromisoformat(anterior["buscado_em"][:10]) if anterior else None

    try:
        ctx = await buscador.buscar(dono.ticker, dono.descricao, desde)
    except RuntimeError as e:
        # Chave ausente ou API fora — mensagem clara, não 500 mudo.
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e)) from None

    achados = [buscador.achado_para_dict(a) for a in ctx.achados]
    await repo.salvar_contexto(pilar_id, ctx.nada_mudou, achados)
    guardado = await repo.ultimo_contexto(pilar_id)
    return ContextoOut(**guardado)
