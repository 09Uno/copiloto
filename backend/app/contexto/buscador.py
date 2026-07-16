"""Buscador de contexto — a "versão honesta" da checagem de pilar qualitativo.

O sistema **não julga** "monopólio regulado ainda vale?". Ele PERGUNTA. Este módulo não muda
isso: ele **lê o que você não tem tempo de ler** e traz as notícias que tocam aquela afirmação,
**citadas**, para VOCÊ julgar.

A regra que mantém tudo honesto — e que é o projeto inteiro em uma linha:

    A IA NUNCA dá o veredito. Ela só FILTRA relevância entre notícias que EXISTEM.

Por isso o desenho é: *nós* buscamos as matérias reais (Google Notícias, com URL e data) e
passamos a lista pronta ao LLM. Ele escolhe as que tocam a afirmação e diz por quê em uma linha
— referenciando pelo número. Não pode inventar fonte (só recebe as que demos), não pode dar
score, não pode dizer "compre". Se nada toca a afirmação, ele responde "nada relevante" — e
silêncio é uma resposta legítima, igual ao vigia.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus
from xml.etree import ElementTree as ET

import httpx

from app.core.config import BACKEND_DIR

_OPENAI = "https://api.openai.com/v1/chat/completions"
_GOOGLE_NEWS = "https://news.google.com/rss/search"
MAX_NOTICIAS = 15  # teto de matérias enviadas ao LLM — controla custo e ruído

# Termo de busca por ticker. O nome comum acha muito mais que o código na imprensa
# ("Sanepar" > "SAPR4"). Fallback: o próprio ticker. FIIs a imprensa cita pelo código mesmo.
NOMES: dict[str, str] = {
    "ITUB4": "Itaú Unibanco", "ITUB3": "Itaú Unibanco",
    "BBDC4": "Bradesco", "BBDC3": "Bradesco",
    "TAEE3": "Taesa", "TAEE4": "Taesa", "TAEE11": "Taesa",
    "SAPR4": "Sanepar", "SAPR3": "Sanepar", "SAPR11": "Sanepar",
    "CMIG4": "Cemig", "CMIG3": "Cemig",
    "KLBN4": "Klabin", "KLBN3": "Klabin", "KLBN11": "Klabin",
    "ROXO34": "Nubank", "BTC": "Bitcoin",
    "GOLD11": "GOLD11 ouro",
}


def _limpar_chave(v: str | None) -> str | None:
    """Tira espaço e ASPAS acidentais. `OPENAI_API_KEY="sk-..."` no .env poria as aspas
    dentro da chave e a OpenAI devolveria 401 — a pegadinha mais comum."""
    if not v:
        return None
    v = v.strip().strip('"').strip("'").strip()
    return v or None


def _api_key() -> str | None:
    if v := os.getenv("OPENAI_API_KEY"):
        return _limpar_chave(v)
    env = BACKEND_DIR / ".env"
    if env.exists():
        for linha in env.read_text(encoding="utf-8").splitlines():
            if linha.strip().startswith("OPENAI_API_KEY="):
                return _limpar_chave(linha.split("=", 1)[1])
    return None


def _modelo() -> str:
    return os.getenv("OPENAI_MODEL", "gpt-4o-mini")


def disponivel() -> bool:
    """O buscador só liga com a chave configurada. Sem ela, a tela mostra 'ligue a busca'."""
    return bool(_api_key())


def termo_busca(ticker: str) -> str:
    return NOMES.get(ticker.upper(), ticker.upper())


@dataclass(frozen=True)
class Achado:
    resumo: str            # a frase do LLM: por que esta matéria toca a afirmação
    url: str
    fonte: str
    data: str | None       # ISO (YYYY-MM-DD) quando dá para saber
    relevancia: str        # "a favor" | "contra" | "contexto"


@dataclass(frozen=True)
class Contexto:
    nada_mudou: bool
    achados: list[Achado]


async def _noticias(termo: str, desde: date | None) -> list[dict]:
    """Notícias reais do Google Notícias (RSS, PT-BR). Sem chave, sem custo."""
    dias = 30
    if desde:
        dias = max(1, min(60, (datetime.now(UTC).date() - desde).days or 1))
    q = f"{termo} when:{dias}d"
    url = f"{_GOOGLE_NEWS}?q={quote_plus(q)}&hl=pt-BR&gl=BR&ceid=BR:pt-419"

    async with httpx.AsyncClient(timeout=20, headers={"User-Agent": "copiloto/0.1"}) as cli:
        r = await cli.get(url)
    return _parse_rss(r.content) if r.status_code == 200 else []


def _parse_rss(conteudo: bytes) -> list[dict]:
    """Extrai (título, url, fonte, data) do RSS do Google Notícias. Puro — testável sem rede."""
    try:
        raiz = ET.fromstring(conteudo)
    except ET.ParseError:
        return []

    itens: list[dict] = []
    for item in raiz.iterfind(".//item"):
        titulo = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        if not titulo or not link:
            continue
        fonte_el = item.find("source")
        fonte = (fonte_el.text or "").strip() if fonte_el is not None else ""
        pub = item.findtext("pubDate")
        data_iso = None
        if pub:
            try:
                data_iso = parsedate_to_datetime(pub).date().isoformat()
            except (TypeError, ValueError):
                data_iso = None
        itens.append({"titulo": titulo, "url": link, "fonte": fonte, "data": data_iso})
        if len(itens) >= MAX_NOTICIAS:
            break
    return itens


_SISTEMA = (
    "Você é um assistente de PESQUISA para um investidor. Sua ÚNICA função é filtrar notícias "
    "por relevância a uma AFIRMAÇÃO específica. Você NUNCA julga se a afirmação é verdadeira ou "
    "falsa, NUNCA recomenda comprar, vender ou manter, e NUNCA dá nota ou score.\n"
    "Receberá a AFIRMAÇÃO e uma lista NUMERADA de notícias reais. Selecione apenas as que tocam "
    "DIRETAMENTE a afirmação — a favor ou contra — e diga em UMA frase curta por quê. Use SOMENTE "
    "as notícias fornecidas, referenciando pelo número; nunca invente uma notícia. Se NENHUMA "
    "tocar a afirmação, responda nada_relevante=true e achados=[].\n"
    'Responda só JSON: {"nada_relevante": bool, "achados": '
    '[{"n": int, "relevancia": "a favor"|"contra"|"contexto", "porque": "..."}]}'
)


async def _filtrar(afirmacao: str, empresa: str, noticias: list[dict]) -> Contexto:
    lista = "\n".join(
        f"{i}. [{n['data'] or 's/data'}] {n['titulo']} ({n['fonte'] or '?'})"
        for i, n in enumerate(noticias, 1)
    )
    usuario = (
        f"AFIRMAÇÃO (o motivo pelo qual o investidor tem {empresa}):\n\"{afirmacao}\"\n\n"
        f"NOTÍCIAS:\n{lista}\n\nResponda só o JSON."
    )

    async with httpx.AsyncClient(timeout=60) as cli:
        r = await cli.post(
            _OPENAI,
            headers={"Authorization": f"Bearer {_api_key()}"},
            json={
                "model": _modelo(),
                "temperature": 0,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": _SISTEMA},
                    {"role": "user", "content": usuario},
                ],
            },
        )
    if r.status_code != 200:
        raise RuntimeError(f"OpenAI {r.status_code}: {r.text[:200]}")

    conteudo = r.json()["choices"][0]["message"]["content"]
    return _montar(json.loads(conteudo), noticias)


def _montar(dados: dict, noticias: list[dict]) -> Contexto:
    """Casa a resposta do LLM com as notícias REAIS. O índice tem de existir — se o LLM citar
    um número que não demos, ele inventou, e a gente descarta. É a trava anti-alucinação."""
    achados: list[Achado] = []
    for a in dados.get("achados", []):
        try:
            n = noticias[int(a["n"]) - 1]
        except (KeyError, ValueError, IndexError, TypeError):
            continue
        achados.append(Achado(
            resumo=str(a.get("porque", "")).strip(),
            url=n["url"], fonte=n["fonte"], data=n["data"],
            relevancia=str(a.get("relevancia", "contexto")).strip(),
        ))
    return Contexto(nada_mudou=(not achados), achados=achados)


async def buscar(ticker: str, afirmacao: str, desde: date | None = None) -> Contexto:
    """Busca o que a imprensa diz que toca ESTA afirmação, desde a última checagem.

    Levanta RuntimeError se a chave não estiver configurada ou a API falhar — a rota traduz
    isso em uma mensagem clara ("ligue a busca" / "não consegui buscar agora").
    """
    if not disponivel():
        raise RuntimeError(
            "Busca de contexto desligada: defina OPENAI_API_KEY em backend/.env para ligar."
        )
    empresa = termo_busca(ticker)
    noticias = await _noticias(empresa, desde)
    if not noticias:
        return Contexto(nada_mudou=True, achados=[])  # sem notícia, sem gastar token
    return await _filtrar(afirmacao, empresa, noticias)


def achado_para_dict(a: Achado) -> dict:
    return asdict(a)
