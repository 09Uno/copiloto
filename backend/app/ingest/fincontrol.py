"""FinControl — a carteira real do usuário.

**O FinControl é a fonte da verdade. Este sistema SÓ LÊ, nunca escreve.**

Registrar a mesma operação em dois lugares é receita para os dois ficarem desatualizados — e
aí o copiloto passa a decidir com base numa carteira que não existe mais. Uma fonte só, e ela
é a que o usuário já mantém.

O que puxamos (`GET /api/summary`, uma chamada):
  · transações  → posição e CUSTO MÉDIO (é ele que ancora o yield-on-cost e o preço teto)
  · proventos   → o que já entrou de verdade
  · renda fixa

Autenticação: o CSRF do FinControl só vale para POST/PUT/DELETE — a leitura passa direto.
Só o login precisa do token, que sai do cookie na primeira visita.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date

import httpx
import pandas as pd

from app.core.config import BACKEND_DIR

CSRF_COOKIE = "csrf-token"
CSRF_HEADER = "x-csrf-token"


@dataclass(frozen=True)
class Posicao:
    ticker: str
    quantidade: float
    custo_medio: float
    categoria: str | None = None

    @property
    def investido(self) -> float:
        return self.quantidade * self.custo_medio


@dataclass
class Carteira:
    posicoes: list[Posicao]
    proventos_por_ticker: dict[str, float]
    transacoes: pd.DataFrame

    def de(self, ticker: str) -> Posicao | None:
        for p in self.posicoes:
            if p.ticker == ticker.upper():
                return p
        return None


def _env(chave: str) -> str | None:
    if v := os.getenv(chave):
        return v
    env = BACKEND_DIR / ".env"
    if env.exists():
        for linha in env.read_text(encoding="utf-8").splitlines():
            linha = linha.strip()
            if linha.startswith(f"{chave}="):
                return linha.split("=", 1)[1].strip()
    return None


def _cliente() -> tuple[httpx.Client, str]:
    url = (_env("FINCONTROL_URL") or "").rstrip("/")
    user = _env("FINCONTROL_USER")
    senha = _env("FINCONTROL_PASS")
    if not (url and user and senha):
        raise RuntimeError(
            "Faltam credenciais do FinControl em backend/.env:\n"
            "  FINCONTROL_URL=https://fincontrol.codetoyou.tech\n"
            "  FINCONTROL_USER=...\n"
            "  FINCONTROL_PASS=..."
        )

    c = httpx.Client(base_url=url, timeout=60.0, follow_redirects=True)

    # O cookie de CSRF nasce na primeira visita; o login (POST) exige ecoá-lo no header.
    c.get("/")
    token = c.cookies.get(CSRF_COOKIE)

    r = c.post(
        "/api/auth/login",
        json={"username": user, "password": senha},
        headers={CSRF_HEADER: token} if token else {},
    )
    if r.status_code != 200:
        raise RuntimeError(f"login no FinControl falhou: HTTP {r.status_code} — {r.text[:160]}")

    return c, url


def _custo_medio(transacoes: pd.DataFrame) -> list[Posicao]:
    """Posição e custo médio ponderado — o padrão brasileiro, e o que o painel dele mostra.

    A VENDA NÃO MEXE NO CUSTO MÉDIO. Ela reduz a quantidade e realiza lucro/prejuízo; o preço
    médio do que sobra continua o mesmo. Recalcular o custo na venda (erro comum) inflaria ou
    esvaziaria o yield-on-cost sem que nada tenha acontecido de verdade.
    """
    estado: dict[str, dict] = {}

    for _, t in transacoes.sort_values("data").iterrows():
        tk = str(t["ativo"]).strip().upper()
        q = float(t["quantidade"] or 0)
        p = float(t["preco"] or 0)
        custos = float(t.get("custos") or 0)
        if q <= 0:
            continue

        e = estado.setdefault(
            tk, {"qtd": 0.0, "custo": 0.0, "categoria": t.get("categoria")}
        )

        if str(t["tipo"]).upper().startswith("C"):
            total = q * p + custos
            e["custo"] = (e["qtd"] * e["custo"] + total) / (e["qtd"] + q)
            e["qtd"] += q
        else:
            e["qtd"] = max(0.0, e["qtd"] - q)
            if e["qtd"] <= 1e-9:
                e["custo"] = 0.0  # zerou a posição

    return [
        Posicao(tk, e["qtd"], e["custo"], e["categoria"])
        for tk, e in estado.items()
        if e["qtd"] > 1e-9
    ]


def puxar() -> Carteira:
    """A carteira real, direto do FinControl."""
    c, _ = _cliente()
    try:
        r = c.get("/api/summary")
        r.raise_for_status()
        dados = r.json().get("data", {})
    finally:
        c.close()

    tx = pd.DataFrame(dados.get("transactions", []))
    if tx.empty:
        return Carteira([], {}, tx)

    # A data vem como DD/MM/YYYY (string).
    tx["data"] = pd.to_datetime(tx["data"], format="%d/%m/%Y", errors="coerce")
    tx = tx.dropna(subset=["data"])

    proventos: dict[str, float] = {}
    for p in dados.get("proventos", []):
        tk = str(p.get("ativo", "")).strip().upper()
        if tk:
            proventos[tk] = proventos.get(tk, 0.0) + float(p.get("total") or 0)

    return Carteira(
        posicoes=sorted(_custo_medio(tx), key=lambda x: -x.investido),
        proventos_por_ticker=proventos,
        transacoes=tx,
    )


def vendas_no_mes(carteira: Carteira, quando: date | None = None) -> float:
    """Total VENDIDO no mês — a base da isenção de R$ 20 mil em ações."""
    quando = quando or date.today()
    tx = carteira.transacoes
    if tx.empty:
        return 0.0
    m = tx[
        (tx["tipo"].astype(str).str.upper().str.startswith("V"))
        & (tx["data"].dt.month == quando.month)
        & (tx["data"].dt.year == quando.year)
    ]
    return float((m["quantidade"] * m["preco"]).sum()) if len(m) else 0.0
