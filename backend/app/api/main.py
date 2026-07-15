"""A API do copiloto de decisão.

    uvicorn app.api.main:app --reload

Portável de propósito: nenhuma dependência de Supabase. Sobe igual na VPS.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import pool
from app.api.rotas import ativo, autenticacao, carteira, tese


@asynccontextmanager
async def lifespan(_: FastAPI):
    await pool.abrir()
    yield
    await pool.fechar()


app = FastAPI(
    title="Copiloto de Decisão",
    description="Guarde por que você comprou; o sistema avisa quando o motivo deixar de valer.",
    version="0.1.0",
    lifespan=lifespan,
)

# O front (Next.js) roda em outra porta/host. Em produção, restringir à origem real.
_origens = os.getenv("CORS_ORIGENS", "http://localhost:3000").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _origens],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(autenticacao.router)
app.include_router(carteira.router)
app.include_router(ativo.router)
app.include_router(tese.router)


@app.get("/api/saude")
async def saude() -> dict:
    return {"ok": True}
