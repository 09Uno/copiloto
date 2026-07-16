"""Rota do resumo diário — o texto pronto para o WhatsApp.

Feita para ser chamada por um agendador (o n8n do Bruno), não por um humano logado. Por isso a
autenticação é um **token de serviço** (`RESUMO_TOKEN` no .env), enviado no header
`X-Resumo-Token` — não o JWT de 7 dias, que venceria no meio da semana e mataria o cron.

O endpoint só MONTA o texto; quem entrega no WhatsApp é o n8n (Schedule → HTTP → Evolution).
Essa separação mantém a lógica onde estão os dados e o encanamento onde ele já existe.
"""

from __future__ import annotations

import hmac
import os
from datetime import UTC, datetime

from fastapi import APIRouter, Header, HTTPException, status

from app.api import repo
from app.core.config import BACKEND_DIR
from app.resumo import briefing

router = APIRouter(prefix="/api", tags=["resumo"])


def _env(nome: str) -> str | None:
    """Lê de os.environ ou do backend/.env — mesmo padrão do resto (JWT, OpenAI)."""
    if v := os.getenv(nome):
        return v.strip()
    env = BACKEND_DIR / ".env"
    if env.exists():
        for linha in env.read_text(encoding="utf-8").splitlines():
            if linha.strip().startswith(f"{nome}="):
                return linha.split("=", 1)[1].strip() or None
    return None


@router.get("/resumo")
async def resumo(x_resumo_token: str | None = Header(default=None)) -> dict:
    segredo = _env("RESUMO_TOKEN")
    if not segredo:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "resumo desligado: defina RESUMO_TOKEN em backend/.env para ligar.",
        )
    # compare_digest evita vazar o token por tempo de resposta
    if not x_resumo_token or not hmac.compare_digest(x_resumo_token, segredo):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "token de resumo inválido")

    email = _env("RESUMO_EMAIL")
    user = await repo.buscar_por_email(email) if email else None
    if user is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "defina RESUMO_EMAIL em backend/.env com o e-mail da conta a resumir.",
        )

    texto, tem_alertas = await briefing.montar_texto(user.id)
    return {
        "texto": texto,
        "tem_alertas": tem_alertas,
        "gerado_em": datetime.now(UTC).isoformat(),
    }
