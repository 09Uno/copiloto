"""A rota do resumo diário — protegida por token de SERVIÇO (não o JWT de 7 dias)."""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest

from app.resumo import briefing

pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402

from app.api.rotas import resumo as resumo_route  # noqa: E402


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


def test_sem_token_configurado_desliga(cliente, monkeypatch):
    monkeypatch.setattr(resumo_route, "_env", lambda _: None)
    r = cliente.get("/api/resumo", headers={"X-Resumo-Token": "qualquer"})
    assert r.status_code == 503
    assert "RESUMO_TOKEN" in r.text


def test_token_errado_e_recusado(cliente, monkeypatch):
    monkeypatch.setattr(resumo_route, "_env",
                        lambda n: "o-segredo" if n == "RESUMO_TOKEN" else None)
    r = cliente.get("/api/resumo", headers={"X-Resumo-Token": "chute"})
    assert r.status_code == 401


def test_token_certo_devolve_o_texto(cliente, monkeypatch):
    email = f"res_{uuid.uuid4().hex[:10]}@exemplo.com"
    assert cliente.post("/api/auth/cadastro",
                        json={"email": email, "senha": "senha-de-teste-123"}).status_code == 201

    monkeypatch.setattr(resumo_route, "_env",
                        lambda n: {"RESUMO_TOKEN": "o-segredo", "RESUMO_EMAIL": email}.get(n))

    async def fake_texto(user_id, hoje=None):
        return ("📊 *Copiloto — teste*", True)
    monkeypatch.setattr(briefing, "montar_texto", fake_texto)

    r = cliente.get("/api/resumo", headers={"X-Resumo-Token": "o-segredo"})
    assert r.status_code == 200, r.text
    assert r.json()["texto"] == "📊 *Copiloto — teste*"
    assert r.json()["tem_alertas"] is True
    _apagar(email)


def test_formatar_lidera_pelo_urgente_e_cala_quando_tranquilo():
    """Sem alertas → mensagem curta de 'tudo tranquilo'. É o vigia: só fala quando muda."""
    from datetime import date
    texto, alertas = briefing.formatar([], [], date(2026, 7, 16))
    assert not alertas
    assert "Tudo tranquilo" in texto
