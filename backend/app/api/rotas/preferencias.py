"""Rota das preferências — os botões que definem TODO preço de compra.

A meta de yield gera o teto ("acima daqui não serve à minha meta"); a margem gera a folga
abaixo dele. São o critério DO USUÁRIO — é isso que mantém a ferramenta do lado certo da linha
regulatória. Antes desta rota, esses valores existiam no banco mas não havia como o usuário
mexer neles: o produto dizia "o critério é seu" sem dar a alavanca.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.api import repo
from app.api.deps import usuario_atual

router = APIRouter(prefix="/api/preferencias", tags=["preferencias"])


class PreferenciasOut(BaseModel):
    meta_yield_acao: float
    meta_yield_fii: float
    margem_seguranca: float
    email_alertas: bool


class PreferenciasIn(BaseModel):
    # Metas sãs: yield entre 1% e 30% (fora disso o teto vira ficção); margem entre 0 e 90%.
    meta_yield_acao: float = Field(ge=0.01, le=0.30)
    meta_yield_fii: float = Field(ge=0.01, le=0.30)
    margem_seguranca: float = Field(ge=0.0, le=0.90)
    email_alertas: bool = True


@router.get("", response_model=PreferenciasOut)
async def ler(user_id: uuid.UUID = Depends(usuario_atual)) -> PreferenciasOut:
    p = await repo.preferencias(user_id)
    return PreferenciasOut(
        meta_yield_acao=p.meta_yield_acao, meta_yield_fii=p.meta_yield_fii,
        margem_seguranca=p.margem_seguranca, email_alertas=p.email_alertas,
    )


@router.put("", response_model=PreferenciasOut)
async def salvar(
    dados: PreferenciasIn, user_id: uuid.UUID = Depends(usuario_atual)
) -> PreferenciasOut:
    p = await repo.atualizar_preferencias(
        user_id, dados.meta_yield_acao, dados.meta_yield_fii,
        dados.margem_seguranca, dados.email_alertas,
    )
    return PreferenciasOut(
        meta_yield_acao=p.meta_yield_acao, meta_yield_fii=p.meta_yield_fii,
        margem_seguranca=p.margem_seguranca, email_alertas=p.email_alertas,
    )
