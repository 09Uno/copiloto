"""Fluxo da API, ponta a ponta, com um Postgres de verdade (o mesmo do dev).

Não é mock: cadastra um usuário efêmero, exercita as rotas e apaga tudo no fim. Se o banco não
estiver acessível, os testes se auto-pulam — não quebram a suíte de quem roda offline.
"""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest

pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402


def _apagar_usuario(email: str) -> None:
    """Limpeza com conexão PRÓPRIA, em loop novo (asyncio.run) — não toca no pool da API,
    que vive no event loop do TestClient. Misturar os dois dá 'another operation in progress'."""
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
        # O lifespan abre o pool no loop do próprio TestClient — nada de gerir loop na mão.
        with TestClient(app) as c:
            c.get("/api/saude").raise_for_status()
            yield c
    except Exception as e:  # noqa: BLE001 — sem banco, pula o módulo inteiro
        pytest.skip(f"sem banco: {e}")


@pytest.fixture
def logado(cliente):
    email = f"teste_{uuid.uuid4().hex[:12]}@exemplo.com"
    r = cliente.post("/api/auth/cadastro",
                     json={"email": email, "senha": "senha-de-teste-123"})
    assert r.status_code == 201, r.text
    yield {"Authorization": f"Bearer {r.json()['token']}"}
    _apagar_usuario(email)  # cascata leva posições e teses junto


# --------------------------------------------------------------- auth


def test_rota_protegida_sem_token_da_401(cliente):
    assert cliente.get("/api/carteira").status_code == 401


def test_cadastro_e_login(cliente):
    email = f"login_{uuid.uuid4().hex[:12]}@exemplo.com"
    assert cliente.post("/api/auth/cadastro",
                        json={"email": email, "senha": "uma-senha-boa"}).status_code == 201
    # e-mail repetido é recusado
    assert cliente.post("/api/auth/cadastro",
                        json={"email": email, "senha": "outra-senha-valida"}).status_code == 409
    # login com senha errada não entra, e não revela se o e-mail existe
    assert cliente.post("/api/auth/login",
                        json={"email": email, "senha": "errada"}).status_code == 401
    assert cliente.post("/api/auth/login",
                        json={"email": email, "senha": "uma-senha-boa"}).status_code == 200
    _apagar_usuario(email)


# --------------------------------------------------------------- carteira


def test_adicionar_e_listar_posicao(cliente, logado):
    r = cliente.put("/api/carteira/posicao",
                    json={"ticker": "TAEE3", "quantidade": 244, "custo_medio": 13.15},
                    headers=logado)
    assert r.status_code == 200
    assert r.json()["classe"] == "ACAO"

    lst = cliente.get("/api/carteira", headers=logado).json()
    assert len(lst) == 1
    assert lst[0]["ticker"] == "TAEE3"
    assert lst[0]["investido"] == pytest.approx(244 * 13.15)


def test_a_carteira_de_um_usuario_nao_vaza_para_outro(cliente, logado):
    """O isolamento por user_id — o teste que mais importa num multi-tenant."""
    cliente.put("/api/carteira/posicao",
                json={"ticker": "ITUB4", "quantidade": 91, "custo_medio": 40.93},
                headers=logado)

    outro_email = f"outro_{uuid.uuid4().hex[:12]}@exemplo.com"
    tok = cliente.post("/api/auth/cadastro",
                       json={"email": outro_email, "senha": "senha-do-outro"}).json()["token"]

    vista_pelo_outro = cliente.get(
        "/api/carteira", headers={"Authorization": f"Bearer {tok}"}
    ).json()
    assert vista_pelo_outro == [], "o outro usuário NÃO pode ver a carteira alheia"
    _apagar_usuario(outro_email)


# --------------------------------------------------------------- tese


def test_a_tese_RECUSA_vai_subir(cliente, logado):
    """A regra central do produto, agora via HTTP: um pilar tem de ser verificável."""
    r = cliente.post(
        "/api/teses",
        json={"ticker": "TAEE3", "resumo": "boa empresa",
              "pilares": [{"texto": "vai subir"}]},
        headers=logado,
    )
    assert r.status_code == 422
    assert "não é um pilar verificável" in r.text


def test_a_tese_recusa_metrica_inexistente_e_ENSINA(cliente, logado):
    r = cliente.post(
        "/api/teses",
        json={"ticker": "TAEE3", "resumo": "x", "pilares": [{"texto": "lucratividade>10"}]},
        headers=logado,
    )
    assert r.status_code == 422
    assert "payout" in r.text  # a mensagem lista o que existe
