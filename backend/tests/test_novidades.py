"""Feed → WhatsApp: manda só o que é NOVO, e nunca repete.

O contrato: novidade é notícia com URL inédita; ao enviar, a URL vira 'já enviada'; a rodada
seguinte com as mesmas notícias não manda nada. É o vigia — só fala quando muda."""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest

from app.mercado import feed
from app.mercado.feed import Fonte, ItemFeed


def _item(assunto, urls, tipo="ativo"):
    return ItemFeed(tipo=tipo, assunto=assunto, rotulo=assunto, titulo="t", resumo="r",
                    mercado="m", fontes=[Fonte(u, "InfoMoney", "2026-07-16") for u in urls],
                    data="2026-07-16", na_carteira=True)


# --------------------------------------------------------------- unidade


def test_novidade_e_a_URL_inedita():
    itens = [_item("TAEE3", ["a", "b"]), _item("CMIG4", ["c"])]
    novos, urls = feed.filtrar_novos(itens, {"c"})        # c já foi → só TAEE3
    assert [i.assunto for i in novos] == ["TAEE3"]
    assert urls == {"a", "b"}

    novos, _ = feed.filtrar_novos(itens, {"a", "b", "c"})  # tudo enviado → nada
    assert novos == []
    assert feed.formatar_whatsapp(novos) == ""


def test_uma_fonte_nova_ja_torna_o_item_novo():
    itens = [_item("TAEE3", ["a", "nova"])]
    novos, _ = feed.filtrar_novos(itens, {"a"})            # 'nova' é inédita → conta
    assert len(novos) == 1


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

    async def fake_gerar(assuntos):
        return itens
    monkeypatch.setattr(feed, "gerar", fake_gerar)

    r1 = cliente.post("/api/feed/novidades", headers={"X-Resumo-Token": "seg"})
    assert r1.status_code == 200, r1.text
    assert r1.json()["novos"] == 2
    assert "TAEE3" in r1.json()["texto"]

    # mesma rodada de novo → nada novo (as URLs já foram marcadas)
    r2 = cliente.post("/api/feed/novidades", headers={"X-Resumo-Token": "seg"})
    assert r2.json()["novos"] == 0
    assert r2.json()["texto"] == ""

    _apagar(email)
