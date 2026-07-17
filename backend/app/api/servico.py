"""Autenticação de SERVIÇO — para endpoints chamados por um agendador (n8n), não por humano.

O JWT expira em 7 dias e mataria um cron. Estes endpoints usam um token fixo (`RESUMO_TOKEN`
no .env) no header `X-Resumo-Token`, e agem sobre a conta de `RESUMO_EMAIL`. É o mesmo modelo do
resumo diário — aqui vira uma dependência, para o feed e o que mais vier reaproveitarem.
"""

from __future__ import annotations

import hmac
import os

from fastapi import Header, HTTPException, status

from app.api import repo
from app.core.config import BACKEND_DIR


def env(nome: str) -> str | None:
    """Lê de os.environ ou do backend/.env — mesmo padrão do resto (JWT, OpenAI)."""
    if v := os.getenv(nome):
        return v.strip()
    arq = BACKEND_DIR / ".env"
    if arq.exists():
        for linha in arq.read_text(encoding="utf-8").splitlines():
            if linha.strip().startswith(f"{nome}="):
                return linha.split("=", 1)[1].strip() or None
    return None


async def usuario_de_servico(x_resumo_token: str | None = Header(default=None)) -> repo.Usuario:
    segredo = env("RESUMO_TOKEN")
    if not segredo:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "serviço desligado: defina RESUMO_TOKEN em backend/.env para ligar.",
        )
    if not x_resumo_token or not hmac.compare_digest(x_resumo_token, segredo):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "token de serviço inválido")

    email = env("RESUMO_EMAIL")
    user = await repo.buscar_por_email(email) if email else None
    if user is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "defina RESUMO_EMAIL em backend/.env com o e-mail da conta.",
        )
    return user
