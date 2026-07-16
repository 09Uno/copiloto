"""Rota do ativo: métricas, preço teto e simulação de aporte.

O teto vem da meta de yield DO USUÁRIO — é isso que mantém a ferramenta do lado certo da linha
regulatória: o critério é dele, não uma recomendação nossa. A rota **nunca** devolve "compre",
"venda" nem "score".
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.api import avaliador, repo
from app.api.deps import usuario_atual
from app.ativos import base as ab
from app.ativos.decisao import Posicao, ZonaCompra, simular, zona_de_compra

router = APIRouter(prefix="/api/ativo", tags=["ativo"])


class MetricaOut(BaseModel):
    nome: str
    rotulo: str
    valor: float | None
    texto: str


class TetoOut(BaseModel):
    valor: float
    criterio: str
    abaixo: bool
    margem_pct: float | None


class CompraOut(BaseModel):
    """Preço de compra (teto com margem) e onde o preço de hoje está frente a ele."""

    preco_compra: float
    teto: float
    margem_seguranca: float
    estado: str               # "COMPRA" | "JUSTO" | "CARO"
    falta_cair_pct: float | None

    @classmethod
    def de(cls, z: ZonaCompra) -> CompraOut:
        return cls(
            preco_compra=z.preco_compra, teto=z.teto,
            margem_seguranca=z.margem_seguranca, estado=z.estado.value,
            falta_cair_pct=z.falta_cair_pct,
        )


class AvaliacaoOut(BaseModel):
    ticker: str
    classe: str
    preco: float | None
    metricas: list[MetricaOut]
    teto: TetoOut | None
    compra: CompraOut | None       # preço de compra com margem + zona
    alertas: list[str]
    sem_criterio: str | None
    # o que a tese pode verificar nesta classe
    metricas_verificaveis: dict[str, str]


class AporteOut(BaseModel):
    veredito: str
    custo_medio_antes: float
    custo_medio_depois: float
    yoc_antes: float | None
    yoc_depois: float | None
    yield_atual: float | None
    motivos: list[str]


@router.get("/{ticker}", response_model=AvaliacaoOut)
async def avaliar_ativo(
    ticker: str, user_id: uuid.UUID = Depends(usuario_atual)
) -> AvaliacaoOut:
    tk = ticker.upper().strip()
    classe = ab.classificar(tk)
    meta = await repo.meta_yield(user_id, classe.value)
    margem = await repo.margem_seguranca(user_id)
    av = avaliador.avaliar(tk, meta)

    z = zona_de_compra(av, margem)
    impl = ab.para(classe)
    return AvaliacaoOut(
        ticker=av.ticker,
        classe=av.classe.value,
        preco=av.preco,
        metricas=[
            MetricaOut(nome=m.nome, rotulo=m.rotulo, valor=m.valor, texto=str(m))
            for m in av.metricas.values()
            if m.valor is not None
        ],
        teto=(
            TetoOut(valor=av.teto.valor, criterio=av.teto.criterio,
                    abaixo=bool(av.abaixo_do_teto), margem_pct=av.margem_pct)
            if av.teto else None
        ),
        compra=CompraOut.de(z) if z else None,
        alertas=list(av.alertas),
        sem_criterio=av.sem_criterio,
        metricas_verificaveis=impl.metricas_disponiveis() if impl else {},
    )


@router.get("/{ticker}/aporte", response_model=AporteOut | None)
async def simular_aporte(
    ticker: str,
    quantidade: float = Query(gt=0),
    user_id: uuid.UUID = Depends(usuario_atual),
) -> AporteOut | None:
    tk = ticker.upper().strip()
    classe = ab.classificar(tk)
    meta = await repo.meta_yield(user_id, classe.value)
    av = avaliador.avaliar(tk, meta)

    # Usa a posição atual do usuário (se tiver) para o custo médio e o yield-on-cost.
    atual = next((p for p in await repo.posicoes(user_id) if p.ticker == tk), None)
    pos = Posicao(tk, atual.quantidade, atual.custo_medio) if atual else None

    ap = simular(av, pos, quantidade)
    if ap is None:
        return None
    return AporteOut(
        veredito=ap.veredito,
        custo_medio_antes=ap.custo_medio_antes,
        custo_medio_depois=ap.custo_medio_depois,
        yoc_antes=ap.yoc_antes, yoc_depois=ap.yoc_depois, yield_atual=ap.yield_atual,
        motivos=list(ap.motivos),
    )
