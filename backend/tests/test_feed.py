"""O feed de mercado — os contratos que são o produto, e por isso viram teste.

  1. A IA só fala do que EXISTE: um número de fonte inventado é DESCARTADO (anti-alucinação),
     e "relevante" sem fonte real vira nada — não um card com URL fabricada.
  2. O giro (descoberta) não repete um ativo que o usuário já acompanha.
  3. Sem chave, a resposta ENSINA (503), não é um 500 mudo.
"""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest

from app.mercado import feed


# --------------------------------------------------------------- unidade (sem rede, sem banco)

_NOTICIAS = [
    {"titulo": "Bancos elevam preço-alvo da Vibra", "url": "http://a",
     "fonte": "InfoMoney", "data": "2026-07-16"},
    {"titulo": "Copel muda política de alavancagem", "url": "http://b",
     "fonte": "Valor", "data": "2026-07-15"},
]


def test_fontes_DESCARTA_indice_que_o_LLM_inventou():
    """A trava anti-alucinação: o LLM só cita notícias que demos. Índice fora da lista é
    descartado — nunca vira uma fonte com URL fabricada."""
    fontes = feed._fontes([1, 9], _NOTICIAS)  # 9 não existe
    assert len(fontes) == 1
    assert fontes[0].url == "http://a"


def test_fontes_dedup_por_url():
    fontes = feed._fontes([1, 1, 2], _NOTICIAS)
    assert [f.url for f in fontes] == ["http://a", "http://b"]


def test_item_none_quando_irrelevante():
    assert feed._item_de_dados(
        {"relevante": False}, "ativo", "VBBR3", "Vibra (VBBR3)", True, _NOTICIAS
    ) is None


def test_item_none_quando_relevante_mas_sem_fonte_real():
    """'relevante' sem citar nenhuma notícia válida = o LLM não se ancorou; não vira card."""
    dados = {"relevante": True, "titulo": "x", "resumo": "y", "mercado": "z", "fontes": [99]}
    assert feed._item_de_dados(
        dados, "ativo", "VBBR3", "Vibra (VBBR3)", True, _NOTICIAS
    ) is None


def test_item_ok_pega_data_mais_recente():
    dados = {"relevante": True, "titulo": "Alta da Vibra", "resumo": "bancos elevam alvo",
             "mercado": "sinal para o setor de distribuição", "fontes": [2, 1]}
    item = feed._item_de_dados(dados, "ativo", "VBBR3", "Vibra (VBBR3)", True, _NOTICIAS)
    assert item is not None
    assert item.na_carteira is True
    assert item.data == "2026-07-16"          # a mais recente entre as fontes citadas
    assert len(item.fontes) == 2


def test_descoberta_PULA_ticker_que_o_usuario_ja_acompanha():
    dados = {"itens": [
        {"ticker": "VBBR3", "empresa": "Vibra", "titulo": "t", "resumo": "r",
         "mercado": "m", "fontes": [1]},                       # já é "seu ativo" → pula
        {"ticker": "CPLE3", "empresa": "Copel", "titulo": "t", "resumo": "r",
         "mercado": "m", "fontes": [2]},                       # novo → entra
    ]}
    itens = feed._itens_descoberta(dados, _NOTICIAS, excluir={"VBBR3"})
    assert [i.assunto for i in itens] == ["CPLE3"]
    assert itens[0].tipo == "descoberta"
    assert itens[0].rotulo == "Copel (CPLE3)"


def test_descoberta_descarta_item_sem_fonte_valida():
    dados = {"itens": [{"ticker": "XPTO3", "empresa": "X", "titulo": "t", "resumo": "r",
                        "mercado": "m", "fontes": [42]}]}
    assert feed._itens_descoberta(dados, _NOTICIAS, excluir=set()) == []


# --------------------------------------------------------------- API (banco real; auto-pula)

pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture(scope="module")
def cliente():
    os.environ.setdefault("JWT_SECRET", "teste-" + uuid.uuid4().hex)
    from app.api.main import app
    try:
        with TestClient(app) as c:
            c.get("/api/saude").raise_for_status()
            yield c
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"sem banco: {e}")


@pytest.fixture
def usuario(cliente):
    email = f"feed_{uuid.uuid4().hex[:12]}@exemplo.com"
    tok = cliente.post("/api/auth/cadastro",
                       json={"email": email, "senha": "senha-de-teste-123"}).json()["token"]
    yield {"h": {"Authorization": f"Bearer {tok}"}}

    async def _del(c):
        await c.execute("DELETE FROM users WHERE email = $1", email)
    async def _run():
        from app.core import db
        c = await db.connect()
        try:
            await _del(c)
        finally:
            await c.close()
    asyncio.run(_run())


def test_feed_vazio_antes_de_atualizar(cliente, usuario):
    """GET não gasta token: sem atualização anterior, devolve vazio com gerado_em null."""
    r = cliente.get("/api/feed", headers=usuario["h"])
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["gerado_em"] is None
    assert corpo["itens"] == []


def test_sem_chave_o_atualizar_ENSINA(cliente, usuario, monkeypatch):
    """Sem OPENAI_API_KEY, atualizar não é 500 mudo — é 503 dizendo o que fazer."""
    monkeypatch.setattr(feed.buscador, "_api_key", lambda: None)
    r = cliente.post("/api/feed/atualizar", headers=usuario["h"])
    assert r.status_code == 503
    assert "OPENAI_API_KEY" in r.text
