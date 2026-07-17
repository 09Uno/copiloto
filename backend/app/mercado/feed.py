"""O feed de mercado — "o giro" das notícias, com um resumo do que elas podem significar.

Irmão do `app/contexto/buscador.py`, e herda a mesma disciplina anti-alucinação: **nós**
buscamos as matérias reais (Google Notícias, com URL e data) e passamos a lista numerada ao LLM;
ele só pode falar sobre o que recebeu, citando pelo número. Se citar um número que não demos,
ele inventou, e a gente descarta.

A diferença para o buscador é um passo a mais que o dono pediu de propósito: além do RESUMO
factual da notícia, o LLM diz **o que aquilo pode significar para o setor/mercado**. Isso é
interpretação — mas fica presa a duas amarras para não virar "dica de ação":

  1. É sobre o MERCADO/SETOR, nunca "compre/venda TICKER". Preço-alvo é do analista citado.
  2. Só sai do texto das notícias que EXISTEM — as mesmas travas do buscador.

Três fontes compõem o feed:
  - "ativo"      — os tickers que o usuário TEM ou está DE OLHO (tese sem posição);
  - "descoberta" — o giro do mercado (mudanças de preço-alvo/recomendação), de onde o LLM
                   extrai ativos que apareceram no noticiário e que o usuário ainda não segue;
  - "macro"      — juros/Selic, inflação/IPCA, câmbio, atividade.

O feed é caro de montar (uma chamada de LLM por assunto). Cacheamos em memória por usuário — o
mesmo atalho do `avaliador.py` —, e a atualização é sob demanda (POST), porque cada clique custa
token. Persistir em banco fica para quando houver mais de um worker.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta

import httpx

from app.contexto import buscador

# Temas macro fixos: (chave, rótulo exibido, termo de busca).
MACRO: list[tuple[str, str, str]] = [
    ("MACRO_JUROS", "Juros / Selic", "Selic Copom taxa de juros Brasil"),
    ("MACRO_INFLACAO", "Inflação / IPCA", "IPCA inflação Brasil"),
    ("MACRO_CAMBIO", "Câmbio / Dólar", "dólar câmbio real Brasil"),
    ("MACRO_ATIVIDADE", "Atividade / PIB", "PIB economia atividade Brasil"),
]

# O "giro do mercado": mudanças de recomendação e preço-alvo — a mesma matéria-prima da imagem.
QUERY_DESCOBERTA = 'ações B3 bolsa "preço-alvo" recomendação analistas'

DIAS_FEED = 7          # o feed é sobre o que é NOVO — última semana
MAX_DESCOBERTA = 6     # teto de ativos por giro, para o custo não escalar
CONCORRENCIA = 5       # chamadas de LLM simultâneas — respeita o rate limit e o bolso

# Cache em memória por usuário: user_id (str) → (gerado_em, itens). Some no restart, de propósito.
_cache: dict[str, tuple[datetime, list["ItemFeed"]]] = {}


def disponivel() -> bool:
    """Sem OPENAI_API_KEY o feed nem aparece — mesma regra do buscador."""
    return buscador.disponivel()


@dataclass(frozen=True)
class Fonte:
    url: str
    fonte: str
    data: str | None       # ISO (YYYY-MM-DD) quando dá para saber


@dataclass(frozen=True)
class ItemFeed:
    tipo: str              # "ativo" | "descoberta" | "macro"
    assunto: str           # ticker ("VBBR3") ou chave macro ("MACRO_JUROS")
    rotulo: str            # "Vibra (VBBR3)" | "Juros / Selic"
    titulo: str
    resumo: str            # o que a imprensa está dizendo (factual)
    mercado: str           # o que pode significar para o setor/mercado (contexto, não veredito)
    fontes: list[Fonte]
    data: str | None       # data mais recente entre as fontes — para ordenar
    na_carteira: bool | None  # só faz sentido para tipo "ativo"


# ------------------------------------------------------------------ cache


def cache_de(user_id) -> tuple[datetime, list[ItemFeed]] | None:
    return _cache.get(str(user_id))


def guardar(user_id, itens: list[ItemFeed]) -> datetime:
    gerado_em = datetime.now(UTC)
    _cache[str(user_id)] = (gerado_em, itens)
    return gerado_em


# ------------------------------------------------------------------ LLM


_SISTEMA_ITEM = (
    "Você é um assistente de PESQUISA de mercado para um investidor pessoa física na B3. "
    "Recebe um ASSUNTO (uma empresa/ativo ou um tema macroeconômico) e uma lista NUMERADA de "
    "notícias reais recentes.\n"
    "Usando SOMENTE as notícias fornecidas:\n"
    "1. Se ao menos uma notícia for relevante ao assunto, escreva: 'titulo' curto (até ~8 "
    "palavras); 'resumo' com 1 a 3 frases FACTUAIS do que a imprensa está dizendo (sem opinião "
    "sua); 'mercado' com 1 a 2 frases EQUILIBRADAS sobre o que isso pode significar para o "
    "SETOR/MERCADO, pesando os DOIS lados — o possível efeito positivo E o risco ou custo de "
    "curto prazo (ex.: uma aquisição pode expandir a receita, MAS aumenta a dívida; um corte de "
    "juros alivia o crédito, MAS pode sinalizar economia fraca). Não seja torcedor de um lado só; "
    "havendo contrapartida relevante, aponte-a — é o lado que costuma faltar. É CONTEXTO, não "
    "recomendação. Você NUNCA recomenda comprar, vender ou manter, NUNCA dá preço-alvo "
    "próprio nem nota; se houver preço-alvo/recomendação, deixe explícito que é de um ANALISTA "
    "citado na notícia. Em 'fontes', os NÚMEROS das notícias que você usou.\n"
    "2. Se NENHUMA notícia for relevante ao assunto, responda {\"relevante\": false}.\n"
    "Nunca invente notícia, número ou fato — use apenas os números da lista.\n"
    'Responda só JSON: {"relevante": bool, "titulo": "...", "resumo": "...", "mercado": "...", '
    '"fontes": [int, ...]}'
)

_SISTEMA_DESCOBERTA = (
    "Você é um assistente de PESQUISA de mercado para um investidor na B3. Recebe uma lista "
    "NUMERADA de notícias reais recentes sobre a bolsa brasileira (mudanças de recomendação, "
    "preço-alvo, resultados, cobertura de analistas).\n"
    "Agrupe por EMPRESA/ativo e, para cada empresa com notícia relevante, gere um item usando "
    "SOMENTE as notícias fornecidas: 'ticker' (o código B3 da ação, ex. VBBR3, se der para saber "
    "pela notícia; senão \"\"); 'empresa' (o nome); 'titulo' curto; 'resumo' com 1 a 2 frases "
    "FACTUAIS; 'mercado' com 1 frase EQUILIBRADA do que isso pode significar — o lado positivo E "
    "o risco/custo de curto prazo quando houver (ex.: aquisição pode crescer a receita MAS elevar "
    "a dívida). Não seja torcedor de um lado só. NUNCA recomende comprar/vender/manter; "
    "preço-alvo/recomendação é sempre do "
    "ANALISTA citado. Em 'fontes', os NÚMEROS das notícias usadas.\n"
    f"Traga no máximo {MAX_DESCOBERTA} empresas, priorizando as de notícia mais concreta. Nunca "
    "invente ticker, número ou fato.\n"
    'Responda só JSON: {"itens": [{"ticker": "...", "empresa": "...", "titulo": "...", '
    '"resumo": "...", "mercado": "...", "fontes": [int, ...]}]}'
)


_SISTEMA_BOLETIM = (
    "Você é um analista escrevendo um BOLETIM de mercado para um investidor pessoa física na B3. "
    "Recebe uma lista NUMERADA de notícias reais recentes — sobre os ATIVOS dele, o MERCADO e a "
    "MACRO (juros, inflação, câmbio, atividade).\n"
    "Escreva um texto DETALHADO porém organizado, em 2 parágrafos curtos: o primeiro sobre a "
    "MACRO, o segundo sobre os ATIVOS dele. Para cada ponto relevante diga O QUE aconteceu (com o "
    "dado/número quando houver) e pese os DOIS lados — o efeito positivo E o risco ou custo de "
    "CURTO PRAZO (ex.: uma aquisição cresce a receita MAS aumenta a dívida; um corte de juros "
    "alivia o crédito MAS pode sinalizar economia fraca). Não seja torcedor de um lado só; a "
    "contrapartida é o que costuma faltar.\n"
    "Além do texto, retorne em 'materias' as PRINCIPAIS notícias que você usou (no máximo 6), "
    "cada uma com um 'rotulo' curto (ex.: 'Taesa — aquisição de transmissoras') e 'fonte' (o "
    "NÚMERO da notícia na lista).\n"
    "NUNCA recomende comprar, vender ou manter; NUNCA dê preço-alvo ou nota própria — "
    "preço-alvo/recomendação é sempre de um ANALISTA citado na notícia. Use SOMENTE as notícias "
    "fornecidas; não invente fato, número, empresa nem número de fonte. Se NENHUMA for relevante, "
    '{"vazio": true}.\n'
    'Responda só JSON: {"vazio": bool, "texto": "os 2 parágrafos", '
    '"materias": [{"rotulo": "...", "fonte": int}]}'
)

CAP_BOLETIM = 40   # teto de manchetes por boletim — segura o custo do único LLM
MAX_LINKS = 6      # quantas matérias entram na seção "Leia mais"


def _lista(noticias: list[dict]) -> str:
    return "\n".join(
        f"{i}. [{n['data'] or 's/data'}] {n['titulo']} ({n['fonte'] or '?'})"
        for i, n in enumerate(noticias, 1)
    )


async def _chamar(sistema: str, usuario: str) -> dict:
    async with httpx.AsyncClient(timeout=60) as cli:
        r = await cli.post(
            buscador._OPENAI,
            headers={"Authorization": f"Bearer {buscador._api_key()}"},
            json={
                "model": buscador._modelo(),
                "temperature": 0,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": sistema},
                    {"role": "user", "content": usuario},
                ],
            },
        )
    if r.status_code != 200:
        raise RuntimeError(f"OpenAI {r.status_code}: {r.text[:200]}")
    return json.loads(r.json()["choices"][0]["message"]["content"])


# ------------------------------------------------------------------ montagem (pura, testável)


def _fontes(indices, noticias: list[dict]) -> list[Fonte]:
    """Casa os números citados pelo LLM com as notícias REAIS. Índice fora da lista (o LLM
    inventou) é descartado — a trava anti-alucinação, igual ao `buscador._montar`."""
    out: list[Fonte] = []
    vistos: set[str] = set()
    for i in indices or []:
        try:
            n = noticias[int(i) - 1]
        except (ValueError, IndexError, TypeError):
            continue
        if n["url"] in vistos:
            continue
        vistos.add(n["url"])
        out.append(Fonte(url=n["url"], fonte=n["fonte"], data=n["data"]))
    return out


def _data_max(fontes: list[Fonte]) -> str | None:
    return max((f.data for f in fontes if f.data), default=None)


def _item_de_dados(
    dados: dict, tipo: str, assunto: str, rotulo: str, na_carteira: bool | None,
    noticias: list[dict],
) -> ItemFeed | None:
    if not dados.get("relevante"):
        return None
    fontes = _fontes(dados.get("fontes"), noticias)
    if not fontes:  # "relevante" sem nenhuma fonte real citada → o LLM não se ancorou; descarta
        return None
    return ItemFeed(
        tipo=tipo, assunto=assunto, rotulo=rotulo,
        titulo=str(dados.get("titulo", "")).strip(),
        resumo=str(dados.get("resumo", "")).strip(),
        mercado=str(dados.get("mercado", "")).strip(),
        fontes=fontes, data=_data_max(fontes), na_carteira=na_carteira,
    )


def _itens_descoberta(dados: dict, noticias: list[dict], excluir: set[str]) -> list[ItemFeed]:
    out: list[ItemFeed] = []
    for it in dados.get("itens", []):
        fontes = _fontes(it.get("fontes"), noticias)
        if not fontes:
            continue
        ticker = str(it.get("ticker", "")).upper().strip()
        if ticker and ticker in excluir:   # já está em "seus ativos" — não repete no giro
            continue
        empresa = str(it.get("empresa", "")).strip()
        rotulo = f"{empresa} ({ticker})" if empresa and ticker else (empresa or ticker or "—")
        out.append(ItemFeed(
            tipo="descoberta", assunto=ticker or empresa, rotulo=rotulo,
            titulo=str(it.get("titulo", "")).strip(),
            resumo=str(it.get("resumo", "")).strip(),
            mercado=str(it.get("mercado", "")).strip(),
            fontes=fontes, data=_data_max(fontes), na_carteira=None,
        ))
    return out


# ------------------------------------------------------------------ coleta por assunto


def _tudo_ja_enviado(noticias: list[dict], enviadas: set[str] | None) -> bool:
    """Com a lista de já-enviadas, se NENHUMA notícia é inédita, não há o que resumir — pula o
    LLM. É o que torna a checagem de hora em hora barata: token só quando há notícia nova."""
    return enviadas is not None and all(n["url"] in enviadas for n in noticias)


async def _sintetizar(
    tipo: str, assunto: str, rotulo: str, termo: str, na_carteira: bool | None,
    desde, enviadas: set[str] | None = None,
) -> ItemFeed | None:
    noticias = await buscador._noticias(termo, desde)
    if not noticias or _tudo_ja_enviado(noticias, enviadas):
        return None  # sem notícia (ou nada novo) — sem gastar token
    dados = await _chamar(_SISTEMA_ITEM, f"ASSUNTO: {rotulo}\n\nNOTÍCIAS:\n{_lista(noticias)}")
    return _item_de_dados(dados, tipo, assunto, rotulo, na_carteira, noticias)


async def _descobrir(excluir: set[str], desde, enviadas: set[str] | None = None) -> list[ItemFeed]:
    noticias = await buscador._noticias(QUERY_DESCOBERTA, desde)
    if not noticias or _tudo_ja_enviado(noticias, enviadas):
        return []
    dados = await _chamar(
        _SISTEMA_DESCOBERTA, f"NOTÍCIAS DO MERCADO:\n{_lista(noticias)}"
    )
    return _itens_descoberta(dados, noticias, excluir)


async def gerar(
    assuntos: list[tuple[str, bool]], enviadas: set[str] | None = None
) -> list[ItemFeed]:
    """Monta o feed: os ativos do usuário + macro + descoberta, tudo concorrente.

    `assuntos` = [(ticker, na_carteira)], da carteira ∪ teses ativas. Se `enviadas` (URLs já
    mandadas) for dado, PULA o LLM nos assuntos sem notícia nova — é o modo "checar de hora em
    hora" barato. Sem `enviadas`, regenera tudo (o botão 'atualizar' do painel).
    Levanta RuntimeError se a chave não estiver configurada — a rota traduz em 503 claro.
    """
    if not disponivel():
        raise RuntimeError(
            "Feed desligado: defina OPENAI_API_KEY em backend/.env para ligar."
        )

    desde = datetime.now(UTC).date() - timedelta(days=DIAS_FEED)
    excluir = {t.upper() for t, _ in assuntos}
    sem = asyncio.Semaphore(CONCORRENCIA)

    async def _com_limite(coro):
        async with sem:
            return await coro

    coros = []
    for ticker, na_carteira in assuntos:
        nome = buscador.termo_busca(ticker)
        rotulo = f"{nome} ({ticker})" if nome.upper() != ticker.upper() else ticker
        coros.append(_com_limite(
            _sintetizar("ativo", ticker.upper(), rotulo, nome, na_carteira, desde, enviadas)
        ))
    for chave, rotulo, termo in MACRO:
        coros.append(_com_limite(_sintetizar("macro", chave, rotulo, termo, None, desde, enviadas)))
    coros.append(_com_limite(_descobrir(excluir, desde, enviadas)))

    # Um assunto que falhar (rede/timeout) não pode derrubar o feed inteiro.
    resultados = await asyncio.gather(*coros, return_exceptions=True)

    itens: list[ItemFeed] = []
    for r in resultados:
        if isinstance(r, ItemFeed):
            itens.append(r)
        elif isinstance(r, list):
            itens.extend(x for x in r if isinstance(x, ItemFeed))
        # exceções: ignoradas de propósito (o assunto some do feed, o resto fica)

    # Mais recentes primeiro dentro de cada grupo; grupos na ordem ativo → descoberta → macro.
    ordem = {"ativo": 0, "descoberta": 1, "macro": 2}
    itens.sort(key=lambda i: i.data or "", reverse=True)
    itens.sort(key=lambda i: ordem.get(i.tipo, 9))
    return itens


def para_dict(item: ItemFeed) -> dict:
    return asdict(item)


# ------------------------------------------------------------------ boletim (digest)


async def _novas_do_assunto(rotulo: str, termo: str, desde, enviadas: set[str]) -> list[tuple]:
    ns = await buscador._noticias(termo, desde)
    return [(rotulo, n) for n in ns if n["url"] not in enviadas]


async def boletim(
    assuntos: list[tuple[str, bool]], enviadas: set[str]
) -> tuple[str, set[str]]:
    """Um BOLETIM: coleta o que é novo (todos os assuntos + macro + giro) e faz UMA chamada de LLM
    que escreve um texto corrido, priorizado e com os dois lados. Devolve (texto, urls_cobertas).

    Barato de propósito: 1 chamada de IA por boletim (não uma por assunto). Se nada novo, não
    chama o LLM e devolve ("", set()). As URLs cobertas são marcadas pela rota para não repetir."""
    if not disponivel():
        raise RuntimeError("Feed desligado: defina OPENAI_API_KEY em backend/.env para ligar.")

    desde = datetime.now(UTC).date() - timedelta(days=DIAS_FEED)
    sem = asyncio.Semaphore(CONCORRENCIA)

    async def _lim(coro):
        async with sem:
            return await coro

    tarefas = []
    for ticker, _ in assuntos:
        nome = buscador.termo_busca(ticker)
        rotulo = f"{nome} ({ticker})" if nome.upper() != ticker.upper() else ticker
        tarefas.append(_lim(_novas_do_assunto(rotulo, nome, desde, enviadas)))
    for _chave, rotulo, termo in MACRO:
        tarefas.append(_lim(_novas_do_assunto(rotulo, termo, desde, enviadas)))
    tarefas.append(_lim(_novas_do_assunto("Mercado", QUERY_DESCOBERTA, desde, enviadas)))

    resultados = await asyncio.gather(*tarefas, return_exceptions=True)
    novas = [par for r in resultados if isinstance(r, list) for par in r]
    if not novas:
        return "", set()  # nada novo — nem gasta o LLM

    urls = {n["url"] for _, n in novas}
    novas.sort(key=lambda x: x[1]["data"] or "", reverse=True)
    mostradas = novas[:CAP_BOLETIM]
    lista = "\n".join(
        f"{i}. [{n['data'] or 's/data'}] ({rot}) {n['titulo']} ({n['fonte'] or '?'})"
        for i, (rot, n) in enumerate(mostradas, 1)
    )
    dados = await _chamar(_SISTEMA_BOLETIM, f"NOTÍCIAS NOVAS:\n{lista}")
    texto = "" if dados.get("vazio") else str(dados.get("texto", "")).strip()
    if not texto:
        return "", urls  # LLM não achou nada digno — marca como visto, não manda

    # seção "Leia mais": rótulo do LLM + a URL real da notícia. Índice fora da lista (o LLM
    # inventou) é descartado — a mesma trava anti-alucinação dos outros pontos.
    links: list[str] = []
    vistos: set[str] = set()
    for m in (dados.get("materias") or [])[:MAX_LINKS]:
        try:
            noticia = mostradas[int(m["fonte"]) - 1][1]
        except (KeyError, ValueError, IndexError, TypeError):
            continue
        if noticia["url"] in vistos:
            continue
        vistos.add(noticia["url"])
        rot = str(m.get("rotulo", "")).strip() or noticia["titulo"]
        links.append(f"• *{rot}*\n{noticia['url']}")

    partes = [f"📊 *Boletim — {datetime.now():%d/%m}*", "", texto]
    if links:
        partes += ["", "🔗 *Leia mais*", *links]
    return "\n".join(partes), urls


# ------------------------------------------------------------------ novidades → WhatsApp

_ICONE = {"ativo": "📈", "descoberta": "🔎", "macro": "🌐"}

LIMITE_POR_RODADA = 2  # portal: no máximo 2 notícias por vez; o resto vem nas próximas rodadas


def filtrar_novos(
    itens: list[ItemFeed], enviadas: set[str]
) -> tuple[list[ItemFeed], set[str]]:
    """Só os itens com ao menos uma fonte INÉDITA. Devolve (novos, urls a marcar como enviadas).

    Dedup pela URL: o resumo do LLM muda entre rodadas, a URL da notícia não. Um item que só cita
    notícias já enviadas não é novidade — mesmo que o texto tenha saído diferente."""
    novos = [i for i in itens if any(f.url not in enviadas for f in i.fontes)]
    urls = {f.url for i in novos for f in i.fontes}
    return novos, urls


def _mensagem(i: ItemFeed) -> str:
    """Uma notícia = um card curto e CONSISTENTE de WhatsApp. Hierarquia: assunto → manchete →
    fato → o que significa → fonte. Sem URL crua: o link do Google Notícias é gigante e fica
    horrível no celular; a fonte vai só pelo nome."""
    p = [f"{_ICONE.get(i.tipo, '📰')} *{i.rotulo}*", ""]
    if i.titulo:
        p.append(f"*{i.titulo}*")
    if i.resumo:
        p.append(i.resumo)
    if i.mercado:
        p += ["", f"💡 _{i.mercado}_"]
    if i.fontes and i.fontes[0].fonte:
        p += ["", f"_via {i.fontes[0].fonte}_"]
    return "\n".join(p)


def mensagens_individuais(novos: list[ItemFeed]) -> list[str]:
    """Uma mensagem por item — o n8n manda cada uma separada. Lista vazia = nada novo."""
    return [_mensagem(i) for i in novos]
