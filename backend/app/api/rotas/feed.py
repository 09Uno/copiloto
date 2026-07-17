"""Rota do feed de mercado — "o giro" das notícias dos seus ativos, do mercado e da macro.

`GET /api/feed` devolve o último feed montado (rápido, sem gastar token). `POST /api/feed/atualizar`
é o clique que CUSTA: busca as notícias reais e o LLM resume o que elas dizem e o que podem
significar para o mercado. Manual e sob demanda, como o buscador de contexto — cada atualização
consome token, então quem dispara é o usuário.

A IA aqui interpreta ("o que pode significar pro mercado"), mas presa a duas amarras que moram no
`app/mercado/feed.py`: é sobre o setor/mercado (nunca "compre TICKER") e só fala do que as
notícias reais dizem. Continua não sendo recomendação.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.api import repo
from app.api.deps import usuario_atual
from app.api.servico import usuario_de_servico
from app.mercado import feed

router = APIRouter(prefix="/api/feed", tags=["feed"])


class FonteOut(BaseModel):
    url: str
    fonte: str
    data: str | None


class ItemOut(BaseModel):
    tipo: str
    assunto: str
    rotulo: str
    titulo: str
    resumo: str
    mercado: str
    fontes: list[FonteOut]
    data: str | None
    na_carteira: bool | None


class FeedOut(BaseModel):
    gerado_em: str | None    # null = nunca montado (o front mostra "atualizar feed")
    itens: list[ItemOut]


def _resposta(gerado_em, itens) -> FeedOut:
    return FeedOut(
        gerado_em=gerado_em.isoformat() if gerado_em else None,
        itens=[feed.para_dict(i) for i in itens],
    )


@router.get("/disponivel")
async def disponivel(_: uuid.UUID = Depends(usuario_atual)) -> dict:
    """A tela pergunta antes de mostrar o botão — sem chave, o feed nem liga."""
    return {"disponivel": feed.disponivel()}


@router.get("", response_model=FeedOut)
async def obter(user_id: uuid.UUID = Depends(usuario_atual)) -> FeedOut:
    """O último feed deste usuário (cacheado). Vazio se ele nunca atualizou — sem token gasto."""
    ent = feed.cache_de(user_id)
    if ent is None:
        return FeedOut(gerado_em=None, itens=[])
    return _resposta(*ent)


@router.post("/atualizar", response_model=FeedOut)
async def atualizar(user_id: uuid.UUID = Depends(usuario_atual)) -> FeedOut:
    """Remonta o feed: carteira ∪ teses ativas do usuário + macro + descoberta. Custa token."""
    assuntos = await repo.tickers_acompanhados(user_id)
    try:
        itens = await feed.gerar(assuntos)
    except RuntimeError as e:
        # Chave ausente ou API fora — mensagem clara, não 500 mudo.
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e)) from None
    gerado_em = feed.guardar(user_id, itens)
    return _resposta(gerado_em, itens)


class ColetarOut(BaseModel):
    coletados: int   # quantas notícias novas entraram na fila nesta busca
    na_fila: int     # total esperando para sair


class ProximaOut(BaseModel):
    mensagens: list[str]   # até LIMITE_POR_RODADA, as mais antigas da fila; [] = fila vazia
    enviados: int
    na_fila: int           # quantas ainda restam


@router.post("/coletar", response_model=ColetarOut)
async def coletar(user=Depends(usuario_de_servico)) -> ColetarOut:
    """ESPARSO (ex.: a cada 30 min). Busca notícias, PULA o LLM onde não há nada novo, e
    ENFILEIRA as novas — sem mandar nada. Marca as URLs para não recoletar. Token de serviço.

    Separado do envio de propósito: a busca é o que pesa (Google + LLM), então roda pouco; a
    entrega no WhatsApp sai da fila, rápida, sem tocar em nada externo."""
    assuntos = await repo.tickers_acompanhados(user.id)
    enviadas = await repo.urls_do_feed_enviadas(user.id)
    try:
        itens = await feed.gerar(assuntos, enviadas)   # modo barato: sem token onde não há novidade
    except RuntimeError as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e)) from None

    novos, urls = feed.filtrar_novos(itens, enviadas)
    await repo.marcar_urls_feed(user.id, urls)          # captura: não recoleta a mesma notícia
    await repo.enfileirar_feed(user.id, feed.mensagens_individuais(novos))
    return ColetarOut(coletados=len(novos), na_fila=await repo.tamanho_fila_feed(user.id))


@router.post("/proxima", response_model=ProximaOut)
async def proxima(user=Depends(usuario_de_servico)) -> ProximaOut:
    """FREQUENTE (ex.: a cada 2-3 min). Tira até 2 mensagens da fila (FIFO) e devolve — sem
    buscar nada. É o fio de saída: intervalo curto sem martelar o Google. Token de serviço."""
    msgs = await repo.proximas_da_fila(user.id, feed.LIMITE_POR_RODADA)
    return ProximaOut(
        mensagens=msgs, enviados=len(msgs), na_fila=await repo.tamanho_fila_feed(user.id)
    )


class BoletimOut(BaseModel):
    texto: str   # o boletim pronto; "" = nada novo relevante (o n8n não manda)


@router.post("/boletim", response_model=BoletimOut)
async def boletim(user=Depends(usuario_de_servico)) -> BoletimOut:
    """BOLETIM (ex.: 3x/dia). UMA chamada de LLM que lê o que é novo e escreve um texto corrido,
    priorizado e com os dois lados (efeito x risco de curto prazo). Marca as URLs cobertas para
    não repetir. Token de serviço. É o caminho enxuto: poucas mensagens, pouco token."""
    assuntos = await repo.tickers_acompanhados(user.id)
    enviadas = await repo.urls_do_feed_enviadas(user.id)
    try:
        texto, urls = await feed.boletim(assuntos, enviadas)
    except RuntimeError as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e)) from None
    await repo.marcar_urls_feed(user.id, urls)
    return BoletimOut(texto=texto)
