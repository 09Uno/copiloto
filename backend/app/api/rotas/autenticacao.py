"""Rotas de auth: cadastro e login."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, EmailStr, Field

from app.api import auth, repo

router = APIRouter(prefix="/api/auth", tags=["auth"])


class Cadastro(BaseModel):
    email: EmailStr
    senha: str = Field(min_length=8, max_length=72)  # 72 = teto do bcrypt
    nome: str | None = None


class Login(BaseModel):
    email: EmailStr
    senha: str


class TokenResp(BaseModel):
    token: str
    email: str
    nome: str | None


@router.post("/cadastro", response_model=TokenResp, status_code=201)
async def cadastrar(dados: Cadastro) -> TokenResp:
    if await repo.buscar_por_email(dados.email):
        raise HTTPException(status.HTTP_409_CONFLICT, "e-mail já cadastrado")
    try:
        h = auth.hash_senha(dados.senha)
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e)) from None

    u = await repo.criar_usuario(dados.email, h, dados.nome)
    return TokenResp(token=auth.emitir_token(u.id, u.email), email=u.email, nome=u.nome)


@router.post("/login", response_model=TokenResp)
async def login(dados: Login) -> TokenResp:
    u = await repo.buscar_por_email(dados.email)
    # Mesma resposta para e-mail inexistente e senha errada: não revela quem tem conta.
    if u is None or not auth.conferir_senha(dados.senha, u.senha_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "e-mail ou senha incorretos")

    await repo.marcar_login(u.id)
    return TokenResp(token=auth.emitir_token(u.id, u.email), email=u.email, nome=u.nome)
