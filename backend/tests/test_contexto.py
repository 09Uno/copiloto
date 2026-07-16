"""O buscador de contexto — a "versão honesta" da checagem de pilar qualitativo.

Dois contratos são o produto e por isso viram teste:
  1. A IA só filtra notícias que EXISTEM — um índice inventado é DESCARTADO (anti-alucinação).
  2. Só o dono do pilar busca o contexto dele; sem chave, a resposta é clara, não um 500 mudo.
"""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest

from app.contexto import buscador
from app.contexto.buscador import Contexto


# --------------------------------------------------------------- unidade (sem rede, sem banco)


def test_termo_de_busca_prefere_o_nome_comum():
    assert buscador.termo_busca("SAPR4") == "Sanepar"   # o nome acha mais que o código
    assert buscador.termo_busca("XPTO3") == "XPTO3"     # sem mapa, cai no ticker


def test_montar_DESCARTA_indice_que_o_LLM_inventou():
    """A trava anti-alucinação: o LLM só pode citar notícias que demos. Índice fora da lista
    (ele inventou uma fonte) é descartado — nunca vira um achado com URL fabricada."""
    noticias = [
        {"titulo": "Sanepar corta JCP", "url": "http://a", "fonte": "InfoMoney", "data": "2026-06-25"},
    ]
    dados = {
        "achados": [
            {"n": 1, "relevancia": "contra", "porque": "corte de provento fura a tese de renda"},
            {"n": 9, "relevancia": "a favor", "porque": "notícia que NÃO existe na lista"},
        ]
    }
    ctx = buscador._montar(dados, noticias)
    assert len(ctx.achados) == 1, "o índice 9 (inexistente) tem de ser descartado"
    assert ctx.achados[0].url == "http://a"
    assert ctx.achados[0].relevancia == "contra"
    assert not ctx.nada_mudou


def test_montar_sem_achados_e_nada_mudou():
    ctx = buscador._montar({"achados": []}, [{"titulo": "x", "url": "u", "fonte": "", "data": None}])
    assert ctx.nada_mudou
    assert ctx.achados == []


def test_parse_rss_le_titulo_fonte_e_data():
    rss = b"""<?xml version="1.0"?><rss><channel>
      <item>
        <title>Sanepar (SAPR11) cancela JCP do primeiro semestre</title>
        <link>https://exemplo.com/materia</link>
        <pubDate>Wed, 25 Jun 2026 10:00:00 GMT</pubDate>
        <source url="https://moneytimes.com.br">Money Times</source>
      </item>
      <item><title>sem link</title></item>
    </channel></rss>"""
    itens = buscador._parse_rss(rss)
    assert len(itens) == 1, "o item sem link é ignorado"
    assert itens[0]["fonte"] == "Money Times"
    assert itens[0]["data"] == "2026-06-25"
    assert itens[0]["url"].startswith("https://")


# --------------------------------------------------------------- API (banco real; auto-pula)

pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402

from app.api import auth  # noqa: E402


def _sql(coro):
    """Roda SQL numa conexão PRÓPRIA (loop novo) — não toca no pool do TestClient."""
    async def _run():
        from app.core import db
        c = await db.connect()
        try:
            return await coro(c)
        finally:
            await c.close()
    return asyncio.run(_run())


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
def pilar(cliente):
    """Um usuário com uma tese e um pilar QUALITATIVO, inserido direto (sem passar pela CVM)."""
    email = f"ctx_{uuid.uuid4().hex[:12]}@exemplo.com"
    tok = cliente.post("/api/auth/cadastro",
                       json={"email": email, "senha": "senha-de-teste-123"}).json()["token"]
    user_id = uuid.UUID(auth.validar_token(tok)["sub"])

    async def _ins(c):
        tese_id = await c.fetchval(
            "INSERT INTO teses (user_id, ticker, classe, resumo) "
            "VALUES ($1,$2,$3,$4) RETURNING id",
            user_id, "SAPR4", "ACAO", "saneamento",
        )
        qual = await c.fetchval(
            "INSERT INTO tese_pilares (tese_id, qualitativo, descricao) "
            "VALUES ($1, TRUE, $2) RETURNING id",
            tese_id, "monopólio regulado de saneamento no Paraná",
        )
        verif = await c.fetchval(
            "INSERT INTO tese_pilares (tese_id, metrica, operador, limite, qualitativo) "
            "VALUES ($1,'pvp','<',1.0, FALSE) RETURNING id",
            tese_id,
        )
        return qual, verif

    qual_id, verif_id = _sql(_ins)
    yield {"h": {"Authorization": f"Bearer {tok}"}, "qual": qual_id, "verif": verif_id}

    async def _del(c):
        await c.execute("DELETE FROM users WHERE email = $1", email)
    _sql(_del)


def test_so_o_dono_busca_o_contexto(cliente, pilar):
    # um pilar_id que não existe / não é do usuário → 404, nunca vaza
    r = cliente.post("/api/contexto/pilar/999999999", headers=pilar["h"])
    assert r.status_code == 404


def test_pilar_verificavel_nao_tem_contexto(cliente, pilar):
    r = cliente.post(f"/api/contexto/pilar/{pilar['verif']}", headers=pilar["h"])
    assert r.status_code == 422
    assert "qualitativ" in r.text.lower()


def test_sem_chave_a_resposta_ENSINA(cliente, pilar, monkeypatch):
    """Sem OPENAI_API_KEY, não é 500 mudo — é 503 dizendo o que fazer."""
    monkeypatch.setattr(buscador, "_api_key", lambda: None)
    r = cliente.post(f"/api/contexto/pilar/{pilar['qual']}", headers=pilar["h"])
    assert r.status_code == 503
    assert "OPENAI_API_KEY" in r.text


def test_busca_com_mock_persiste_e_cita(cliente, pilar, monkeypatch):
    """Com a busca mockada: a rota grava e devolve os achados citados. Nada de veredito."""
    from app.contexto.buscador import Achado

    async def fake_buscar(ticker, afirmacao, desde=None):
        return Contexto(
            nada_mudou=False,
            achados=[Achado(resumo="revisão tarifária em análise", url="http://x",
                            fonte="Agência", data="2026-06-01", relevancia="contexto")],
        )

    monkeypatch.setattr(buscador, "buscar", fake_buscar)
    r = cliente.post(f"/api/contexto/pilar/{pilar['qual']}", headers=pilar["h"])
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["nada_mudou"] is False
    assert len(corpo["achados"]) == 1
    assert corpo["achados"][0]["url"] == "http://x"
    assert corpo["buscado_em"]
