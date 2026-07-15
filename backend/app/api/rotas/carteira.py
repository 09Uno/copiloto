"""Rotas da carteira: listar, adicionar posição manual, e sincronizar de uma fonte externa."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.api import repo
from app.api.deps import usuario_atual
from app.ativos import base as ab

router = APIRouter(prefix="/api/carteira", tags=["carteira"])


class PosicaoIn(BaseModel):
    ticker: str = Field(min_length=2, max_length=20)
    quantidade: float = Field(gt=0)
    custo_medio: float = Field(gt=0)


class PosicaoOut(BaseModel):
    ticker: str
    classe: str
    quantidade: float
    custo_medio: float
    investido: float
    fonte: str


class SyncFinControl(BaseModel):
    url: str
    usuario: str
    senha: str


@router.get("", response_model=list[PosicaoOut])
async def listar(user_id: uuid.UUID = Depends(usuario_atual)) -> list[PosicaoOut]:
    return [
        PosicaoOut(
            ticker=p.ticker, classe=p.classe, quantidade=p.quantidade,
            custo_medio=p.custo_medio, investido=p.quantidade * p.custo_medio, fonte=p.fonte,
        )
        for p in await repo.posicoes(user_id)
    ]


@router.put("/posicao", response_model=PosicaoOut)
async def salvar(dados: PosicaoIn, user_id: uuid.UUID = Depends(usuario_atual)) -> PosicaoOut:
    tk = dados.ticker.upper().strip()
    classe = ab.classificar(tk).value
    await repo.upsert_posicao(user_id, tk, classe, dados.quantidade, dados.custo_medio, "MANUAL")
    return PosicaoOut(
        ticker=tk, classe=classe, quantidade=dados.quantidade,
        custo_medio=dados.custo_medio, investido=dados.quantidade * dados.custo_medio,
        fonte="MANUAL",
    )


@router.delete("/posicao/{ticker}", status_code=204)
async def apagar(ticker: str, user_id: uuid.UUID = Depends(usuario_atual)) -> None:
    await repo.apagar_posicao(user_id, ticker)


@router.post("/sync/fincontrol")
async def sync_fincontrol(
    dados: SyncFinControl, user_id: uuid.UUID = Depends(usuario_atual)
) -> dict:
    """Puxa a carteira do FinControl e substitui as posições dessa fonte.

    Não toca no que é MANUAL: o usuário pode ter as duas coisas.
    """
    from app.carteira.fontes import FinControl, _classe

    try:
        c = FinControl().puxar(
            {"url": dados.url, "usuario": dados.usuario, "senha": dados.senha}
        )
    except Exception as e:  # noqa: BLE001 — a mensagem da fonte é o que o usuário precisa ver
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"FinControl: {e}") from None

    novas = [
        (p.ticker, p.classe or _classe(None) or ab.classificar(p.ticker).value,
         p.quantidade, p.custo_medio)
        for p in c.posicoes
    ]
    n = await repo.substituir_posicoes_da_fonte(user_id, "FINCONTROL", novas)
    return {"importadas": n}
