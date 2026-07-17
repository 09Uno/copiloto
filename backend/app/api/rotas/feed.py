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


class NovidadesOut(BaseModel):
    texto: str      # mensagem pronta para o WhatsApp; vazia = nada novo (o n8n não manda)
    novos: int      # quantos itens inéditos nesta rodada


@router.post("/novidades", response_model=NovidadesOut)
async def novidades(user=Depends(usuario_de_servico)) -> NovidadesOut:
    """Para o agendador (n8n): remonta o feed, manda só o que tem fonte INÉDITA e marca como
    enviado. Autenticado por token de serviço (não JWT). Custa token (uma rodada de LLM)."""
    assuntos = await repo.tickers_acompanhados(user.id)
    try:
        itens = await feed.gerar(assuntos)
    except RuntimeError as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e)) from None

    feed.guardar(user.id, itens)  # atualiza o cache do painel de quebra
    enviadas = await repo.urls_do_feed_enviadas(user.id)
    novos, urls = feed.filtrar_novos(itens, enviadas)
    await repo.marcar_urls_feed(user.id, urls)
    return NovidadesOut(texto=feed.formatar_whatsapp(novos), novos=len(novos))
