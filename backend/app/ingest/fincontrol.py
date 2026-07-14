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
    # Provento DECLARADO ≠ provento RECEBIDO. A CMIG4 tem provento com data-com em jun/2026 e
    # pagamento em jun/2027 — é seu, mas não está na conta. Somar os dois num número só faz o
    # "quanto eu já recebi" mentir.
    recebidos: dict[str, float]
    a_receber: dict[str, float]
    transacoes: pd.DataFrame
    renda_fixa: pd.DataFrame

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


def _cliente(
    url: str | None = None, usuario: str | None = None, senha: str | None = None
) -> tuple[httpx.Client, str]:
    """Credenciais explícitas (SaaS, uma por usuário) ou do .env (uso local, um usuário só)."""
    url = (url or _env("FINCONTROL_URL") or "").rstrip("/")
    user = usuario or _env("FINCONTROL_USER")
    senha = senha or _env("FINCONTROL_PASS")
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


RE_ISO = r"^\d{4}-\d{2}-\d{2}"
RE_BR = r"^\d{2}/\d{2}/\d{4}$"

# Abaixo disto, uma inconsistência não é erro — é poeira de arredondamento de cripto.
MATERIAL_BRL = 20.0


def _datas(col: pd.Series) -> pd.Series:
    """**O FinControl grava a data em DOIS formatos misturados** — provável resíduo de migração:

        '03/11/2025'   (DD/MM/YYYY)   30 registros
        '2025-09-05'   (ISO)         120 registros

    Isso já derrubou este código DUAS VEZES, e a segunda foi pior que a primeira:

    1. Com `format="%d/%m/%Y"`, 120 das 150 transações eram descartadas EM SILÊNCIO — a
       carteira saía com um terço do tamanho e nenhum erro aparecia.

    2. Com `format="mixed", dayfirst=True`, o pandas aplicou o `dayfirst` **também às datas
       ISO** e leu `2025-11-06` como ano-DIA-mês → 11 de junho. As datas ficaram EMBARALHADAS:
       uma venda do TAEE11 foi parar ANTES da compra, o saldo bateu no zero, e sobraram 24
       cotas fantasma que não existem. Silencioso e plausível — o pior tipo.

    A saída é não adivinhar: **detectar o formato pelo padrão e parsear cada um com o formato
    exato.**

    (Vale corrigir na origem: qualquer código do FinControl que parseie com formato fixo vai
    fazer o mesmo estrago.)
    """
    s = col.astype(str).str.strip()
    out = pd.Series(pd.NaT, index=s.index, dtype="datetime64[ns]")

    iso = s.str.match(RE_ISO, na=False)
    out[iso] = pd.to_datetime(s[iso].str[:10], format="%Y-%m-%d", errors="coerce")

    br = s.str.match(RE_BR, na=False)
    out[br] = pd.to_datetime(s[br], format="%d/%m/%Y", errors="coerce")

    return out


def _custo_medio(transacoes: pd.DataFrame) -> list[Posicao]:
    """Posição e custo médio ponderado — o padrão brasileiro, e o que o painel dele mostra.

    A VENDA NÃO MEXE NO CUSTO MÉDIO. Ela reduz a quantidade e realiza lucro/prejuízo; o preço
    médio do que sobra continua o mesmo. Recalcular o custo na venda (erro comum) inflaria ou
    esvaziaria o yield-on-cost sem que nada tenha acontecido de verdade.
    """
    estado: dict[str, dict] = {}

    for _, t in transacoes.sort_values("data").iterrows():
        tk = str(t["ativo"]).strip().upper()
        q = float(t["qtd"] or 0)          # o campo é `qtd`, não `quantidade`
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
            # Vender mais do que se tem é IMPOSSÍVEL — só acontece se a ordem das transações
            # estiver errada (foi o que o embaralhamento de datas causou). Truncar em zero
            # ESCONDE o problema e deixa cotas fantasma na carteira. Tem de gritar.
            #
            # **A régua é o VALOR, não a quantidade.** Vender 0,0000079 ETH que não se tem é
            # poeira de arredondamento (R$ 1,50); vender 100 PETR4 que não se tem são R$ 4 mil
            # e um erro de verdade. Um alarme por quantidade encheria a tela de ruído de
            # cripto — e alerta que grita à toa é alerta que você aprende a ignorar, que é a
            # morte de qualquer sistema de aviso.
            excesso = q - e["qtd"]
            if excesso * p > MATERIAL_BRL:
                print(
                    f"  ! {tk}: venda de {q:g} com apenas {e['qtd']:g} em carteira "
                    f"({t['data']:%d/%m/%Y}) — R$ {excesso * p:,.2f} a mais do que existia. "
                    "Ordem das transações ou dado inconsistente."
                )
            e["qtd"] = max(0.0, e["qtd"] - q)
            if e["qtd"] <= 1e-9:
                e["custo"] = 0.0  # zerou a posição

    return [
        Posicao(tk, e["qtd"], e["custo"], e["categoria"])
        for tk, e in estado.items()
        if e["qtd"] > 1e-9
    ]


def puxar(
    url: str | None = None, usuario: str | None = None, senha: str | None = None
) -> Carteira:
    """A carteira real, direto do FinControl."""
    c, _ = _cliente(url, usuario, senha)
    try:
        r = c.get("/api/summary")
        r.raise_for_status()
        dados = r.json().get("data", {})
    finally:
        c.close()

    tx = pd.DataFrame(dados.get("transactions", []))
    rf = pd.DataFrame(dados.get("rendaFixa", []))
    if tx.empty:
        return Carteira([], {}, {}, tx, rf)

    tx["data"] = _datas(tx["data"])

    perdidas = int(tx["data"].isna().sum())
    if perdidas:
        # Perder linha de transação em silêncio = carteira errada. Isto TEM de gritar.
        print(f"  ! {perdidas} transações com data ilegível — carteira incompleta")
    tx = tx.dropna(subset=["data"])

    hoje = pd.Timestamp.today().normalize()
    recebidos: dict[str, float] = {}
    a_receber: dict[str, float] = {}
    for p in dados.get("proventos", []):
        tk = str(p.get("ativo", "")).strip().upper()
        if not tk:
            continue
        valor = float(p.get("total") or 0)
        pago_em = pd.to_datetime(p.get("dataPagamento"), errors="coerce")

        # Declarado mas ainda não pago é SEU — mas não está na conta. Não pode entrar no
        # "quanto eu já recebi", ou o número mente.
        alvo = a_receber if (pd.notna(pago_em) and pago_em > hoje) else recebidos
        alvo[tk] = alvo.get(tk, 0.0) + valor

    return Carteira(
        posicoes=sorted(_custo_medio(tx), key=lambda x: -x.investido),
        recebidos=recebidos,
        a_receber=a_receber,
        transacoes=tx,
        renda_fixa=rf,
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
        # A isenção vale só para AÇÃO. FII paga 20% sempre, sem isenção.
        & (tx["categoria"].astype(str).str.lower().str.startswith("aç"))
    ]
    return float((m["qtd"] * m["preco"]).sum()) if len(m) else 0.0
