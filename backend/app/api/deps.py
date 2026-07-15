"""Dependências compartilhadas das rotas — a principal é "quem é o usuário deste request".

Toda rota protegida recebe `user_id` por injeção. Se o token falta, expira ou é forjado, o
request morre aqui com 401 — nenhuma rota precisa se preocupar com isso.
"""

from __future__ import annotations

import uuid

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.api import auth

_bearer = HTTPBearer(auto_error=False)


async def usuario_atual(
    cred: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> uuid.UUID:
    if cred is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "faça login")
    try:
        payload = auth.validar_token(cred.credentials)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "sessão expirada") from None
    except jwt.InvalidTokenError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "token inválido") from None
    return uuid.UUID(payload["sub"])
