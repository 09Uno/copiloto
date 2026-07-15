"""Autenticação da aplicação — portável, sem Supabase Auth.

A primeira versão do schema dependia de `auth.users` / `auth.uid()`, que só existem no Supabase.
Como o Supabase é temporário (produção vai para Postgres na VPS), o auth passa a ser da própria
aplicação: senha com **bcrypt**, sessão com **JWT** assinado por nós. Roda idêntico nos dois
Postgres — a migração é só trocar a DATABASE_URL.

bcrypt guarda o hash, nunca a senha; e tem um teto de 72 bytes que, se ignorado, aceita
silenciosamente senhas truncadas — por isso o limite é checado na hora do cadastro.
"""

from __future__ import annotations

import os
import time
import uuid

import bcrypt
import jwt

from app.core.config import BACKEND_DIR

ALG = "HS256"
EXPIRA_S = 7 * 24 * 3600  # 7 dias
BCRYPT_MAX = 72           # bcrypt ignora bytes além disto — senha maior seria truncada


def _segredo() -> str:
    if v := os.getenv("JWT_SECRET"):
        return v
    env = BACKEND_DIR / ".env"
    if env.exists():
        for linha in env.read_text(encoding="utf-8").splitlines():
            if linha.strip().startswith("JWT_SECRET="):
                return linha.split("=", 1)[1].strip()
    # Sem segredo configurado, um token forjado seria aceito. Falhar é mais seguro que fingir.
    raise RuntimeError(
        "JWT_SECRET não definido em backend/.env — a API não sobe sem ele.\n"
        "Gere um: python -c \"import secrets; print(secrets.token_hex(32))\""
    )


def hash_senha(senha: str) -> str:
    b = senha.encode("utf-8")
    if len(b) > BCRYPT_MAX:
        raise ValueError(f"senha longa demais (máx. {BCRYPT_MAX} bytes)")
    return bcrypt.hashpw(b, bcrypt.gensalt()).decode("utf-8")


def conferir_senha(senha: str, hash_: str) -> bool:
    try:
        return bcrypt.checkpw(senha.encode("utf-8")[:BCRYPT_MAX], hash_.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def emitir_token(user_id: uuid.UUID | str, email: str) -> str:
    agora = int(time.time())
    return jwt.encode(
        {"sub": str(user_id), "email": email, "iat": agora, "exp": agora + EXPIRA_S},
        _segredo(),
        algorithm=ALG,
    )


def validar_token(token: str) -> dict:
    """Devolve o payload, ou levanta jwt.InvalidTokenError. `exp` é checado automaticamente."""
    return jwt.decode(token, _segredo(), algorithms=[ALG])
