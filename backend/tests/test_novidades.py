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


def test_mensagem_limpa_sem_url_crua():
    """O card tem o assunto e a fonte pelo NOME — nada de URL gigante (fica horrível no celular)."""
    m = feed.mensagens_individuais([_item("TAEE3", ["http://a"], "ativo")])[0]
    assert "TAEE3" in m
    assert "via InfoMoney" in m
    assert "http" not in m, "não pode ter URL crua na mensagem"


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


def test_portal_manda_no_maximo_2_e_enfileira_o_resto(cliente, monkeypatch):
    """Feito portal: 2 por rodada, o resto vem depois, e nada repete."""
    email = f"nov_{uuid.uuid4().hex[:10]}@exemplo.com"
    assert cliente.post("/api/auth/cadastro",
                        json={"email": email, "senha": "senha-de-teste-123"}).status_code == 201
    monkeypatch.setattr(servico, "env",
                        lambda n: {"RESUMO_TOKEN": "seg", "RESUMO_EMAIL": email}.get(n))

    itens = [_item("A", ["u1"]), _item("B", ["u2"]), _item("C", ["u3"])]

    async def fake_gerar(assuntos, enviadas=None):
        return itens
    monkeypatch.setattr(feed, "gerar", fake_gerar)

    r1 = cliente.post("/api/feed/novidades", headers={"X-Resumo-Token": "seg"}).json()
    assert r1["enviados"] == 2 and r1["na_fila"] == 1     # 2 saem, 1 fica na fila
    assert len(r1["mensagens"]) == 2

    r2 = cliente.post("/api/feed/novidades", headers={"X-Resumo-Token": "seg"}).json()
    assert r2["enviados"] == 1 and r2["na_fila"] == 0     # o 3º sai agora

    r3 = cliente.post("/api/feed/novidades", headers={"X-Resumo-Token": "seg"}).json()
    assert r3["enviados"] == 0 and r3["mensagens"] == []  # nada novo

    _apagar(email)
