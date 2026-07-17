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
    assert cliente.post("/api/feed/coletar", headers={"X-Resumo-Token": "x"}).status_code == 503


def test_coletar_enfileira_e_proxima_drena_2_por_vez(cliente, monkeypatch):
    """Coletar (esparso) enfileira e não duplica; proxima (frequente) drena 2 por vez, FIFO."""
    email = f"nov_{uuid.uuid4().hex[:10]}@exemplo.com"
    assert cliente.post("/api/auth/cadastro",
                        json={"email": email, "senha": "senha-de-teste-123"}).status_code == 201
    H = {"X-Resumo-Token": "seg"}
    monkeypatch.setattr(servico, "env",
                        lambda n: {"RESUMO_TOKEN": "seg", "RESUMO_EMAIL": email}.get(n))

    itens = [_item("A", ["u1"]), _item("B", ["u2"]), _item("C", ["u3"])]

    async def fake_gerar(assuntos, enviadas=None):
        return itens
    monkeypatch.setattr(feed, "gerar", fake_gerar)

    col = cliente.post("/api/feed/coletar", headers=H).json()
    assert col["coletados"] == 3 and col["na_fila"] == 3
    col2 = cliente.post("/api/feed/coletar", headers=H).json()   # URLs já marcadas → não duplica
    assert col2["coletados"] == 0 and col2["na_fila"] == 3

    p1 = cliente.post("/api/feed/proxima", headers=H).json()
    assert p1["enviados"] == 2 and p1["na_fila"] == 1            # drena 2 (os mais antigos)
    assert any("*A*" in m for m in p1["mensagens"])              # FIFO: A veio primeiro
    p2 = cliente.post("/api/feed/proxima", headers=H).json()
    assert p2["enviados"] == 1 and p2["na_fila"] == 0
    p3 = cliente.post("/api/feed/proxima", headers=H).json()
    assert p3["enviados"] == 0 and p3["mensagens"] == []         # fila vazia

    _apagar(email)


def test_boletim_uma_chamada_de_llm_e_dedup(cliente, monkeypatch):
    """O boletim faz UMA chamada de LLM (não uma por assunto) e não repete: sem notícia nova, nem
    chama a IA."""
    from app.contexto import buscador
    email = f"bol_{uuid.uuid4().hex[:10]}@exemplo.com"
    assert cliente.post("/api/auth/cadastro",
                        json={"email": email, "senha": "senha-de-teste-123"}).status_code == 201
    H = {"X-Resumo-Token": "seg"}
    monkeypatch.setattr(servico, "env",
                        lambda n: {"RESUMO_TOKEN": "seg", "RESUMO_EMAIL": email}.get(n))

    async def noticias(termo, desde):
        return [{"titulo": "Taesa compra transmissoras", "url": "http://a",
                 "fonte": "InfoMoney", "data": "2026-07-16"}]

    chamou = {"n": 0}

    async def chamar(sistema, usuario):
        chamou["n"] += 1
        return {"vazio": False, "texto": "Taesa avança em transmissão, ao custo de mais dívida."}

    monkeypatch.setattr(feed, "disponivel", lambda: True)
    monkeypatch.setattr(buscador, "_noticias", noticias)
    monkeypatch.setattr(feed, "_chamar", chamar)

    r1 = cliente.post("/api/feed/boletim", headers=H).json()
    assert "Boletim" in r1["texto"] and "dívida" in r1["texto"]
    assert chamou["n"] == 1, "um boletim = uma chamada de LLM"

    r2 = cliente.post("/api/feed/boletim", headers=H).json()
    assert r2["texto"] == ""                       # url já coberta → nada novo
    assert chamou["n"] == 1, "sem notícia nova, não chama o LLM"

    _apagar(email)
