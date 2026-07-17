"""Feed → WhatsApp: uma mensagem por notícia NOVA, checado de hora em hora, sem repetir e sem
gastar token à toa.

Contratos que viram teste:
  1. Novidade é notícia com URL inédita; ao enviar, a URL vira 'já enviada'; a rodada seguinte
     com as mesmas notícias não manda nada.
  2. Se um assunto não tem notícia nova, o LLM NEM é chamado (a checagem de 1h tem de ser barata).
"""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest

from app.mercado import feed
from app.mercado.feed import Fonte, ItemFeed


def _item(assunto, urls, tipo="ativo"):
    return ItemFeed(tipo=tipo, assunto=assunto, rotulo=assunto, titulo="titulo", resumo="resumo",
                    mercado="pode significar X",
                    fontes=[Fonte(u, "InfoMoney", "2026-07-16") for u in urls],
                    data="2026-07-16", na_carteira=True)


# --------------------------------------------------------------- unidade


def test_novidade_e_a_URL_inedita():
    itens = [_item("TAEE3", ["a", "b"]), _item("CMIG4", ["c"])]
    novos, urls = feed.filtrar_novos(itens, {"c"})        # c já foi → só TAEE3
    assert [i.assunto for i in novos] == ["TAEE3"]
    assert urls == {"a", "b"}

    novos, _ = feed.filtrar_novos(itens, {"a", "b", "c"})  # tudo enviado → nada
    assert novos == []
    assert feed.mensagens_individuais(novos) == []


def test_uma_mensagem_por_item_com_link():
    msgs = feed.mensagens_individuais([_item("TAEE3", ["http://a"], "ativo"),
                                       _item("VBBR3", ["http://y"], "descoberta")])
    assert len(msgs) == 2
    assert "TAEE3" in msgs[0] and "http://a" in msgs[0]
    assert "VBBR3" in msgs[1]


def test_gerar_PULA_o_LLM_quando_nada_novo(monkeypatch):
    """A economia que faz a checagem de 1h valer a pena: se as notícias já foram todas enviadas,
    não gasta uma chamada de IA sequer."""
    from app.contexto import buscador
    chamou_llm = {"n": 0}

    async def noticias_velhas(termo, desde):
        return [{"titulo": "x", "url": "http://ja", "fonte": "F", "data": "2026-07-16"}]

    async def spy(*a, **k):
        chamou_llm["n"] += 1
        return {"relevante": False}

    monkeypatch.setattr(feed, "disponivel", lambda: True)
    monkeypatch.setattr(buscador, "_noticias", noticias_velhas)
    monkeypatch.setattr(feed, "_chamar", spy)

    itens = asyncio.run(feed.gerar([("TAEE3", True)], enviadas={"http://ja"}))
    assert itens == []
    assert chamou_llm["n"] == 0, "não pode chamar o LLM se nenhuma notícia é nova"


# --------------------------------------------------------------- API (banco real; auto-pula)

pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402

from app.api import servico  # noqa: E402


def _apagar(email: str) -> None:
    async def _run():
        from app.core import db
        c = await db.connect()
        try:
            await c.execute("DELETE FROM users WHERE email = $1", email)
        finally:
            await c.close()
    asyncio.run(_run())


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


def test_sem_token_desliga(cliente, monkeypatch):
    monkeypatch.setattr(servico, "env", lambda _: None)
    assert cliente.post("/api/feed/novidades", headers={"X-Resumo-Token": "x"}).status_code == 503


def test_manda_so_o_novo_e_nao_repete(cliente, monkeypatch):
    email = f"nov_{uuid.uuid4().hex[:10]}@exemplo.com"
    assert cliente.post("/api/auth/cadastro",
                        json={"email": email, "senha": "senha-de-teste-123"}).status_code == 201
    monkeypatch.setattr(servico, "env",
                        lambda n: {"RESUMO_TOKEN": "seg", "RESUMO_EMAIL": email}.get(n))

    itens = [_item("TAEE3", ["http://a"]), _item("CMIG4", ["http://b"])]

    async def fake_gerar(assuntos, enviadas=None):
        return itens
    monkeypatch.setattr(feed, "gerar", fake_gerar)

    r1 = cliente.post("/api/feed/novidades", headers={"X-Resumo-Token": "seg"})
    assert r1.status_code == 200, r1.text
    assert r1.json()["novos"] == 2
    assert len(r1.json()["mensagens"]) == 2
    assert any("TAEE3" in m for m in r1.json()["mensagens"])

    # mesma rodada de novo → nada novo (as URLs já foram marcadas)
    r2 = cliente.post("/api/feed/novidades", headers={"X-Resumo-Token": "seg"})
    assert r2.json()["novos"] == 0
    assert r2.json()["mensagens"] == []

    _apagar(email)
