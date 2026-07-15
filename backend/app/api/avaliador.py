"""Avaliar um ativo, com cache — a ponte entre a API e o motor que já existe.

Carregar o painel da CVM (milhões de linhas) a cada request seria absurdo. Aqui ele é lido UMA
vez e reaproveitado. As avaliações por ticker também são memoizadas por algumas horas — os
fundamentos mudam uma vez por trimestre, o preço muda no dia, e ninguém decide compra de
dividendo no susto.

**Nota de arquitetura:** o caminho definitivo é a esteira (Python, 1x/dia) escrever a tabela
`fundamentos` e a API só LER dela — aí a API não carrega CVM nenhuma. Este avaliador em memória
é o atalho para o MVP rodar ponta a ponta hoje; quando o writer da esteira existir, ele sai.
"""

from __future__ import annotations

import threading
import time

from app.ativos import base as ab
from app.ativos.acao import Acao
from app.ativos.base import Avaliacao
from app.ativos.fii import FII
from app.ativos.sem_criterio import ETF, Cripto, RendaFixa

_lock = threading.Lock()
_pronto = False
_cache: dict[tuple[str, int], tuple[float, Avaliacao]] = {}
TTL_S = 6 * 3600


def _garantir_registro() -> None:
    global _pronto
    if _pronto:
        return
    with _lock:
        if _pronto:
            return
        from datetime import UTC, datetime

        from app.ingest import cvm, cvm_fii

        ano = datetime.now(UTC).year
        ab.registrar(Acao(cvm.load(list(range(ano - 5, ano + 1))), cvm.mapa_tickers()))
        ab.registrar(FII(cvm_fii.load([ano - 1, ano])))
        for c in (Cripto(), ETF(), RendaFixa()):
            ab.registrar(c)
        _pronto = True


def _preco(ticker: str) -> float | None:
    import yfinance as yf

    sufixo = "" if ab.classificar(ticker) is ab.Classe.CRIPTO else ".SA"
    try:
        info = yf.Ticker(f"{ticker}{sufixo}").info or {}
        return info.get("currentPrice") or info.get("regularMarketPrice")
    except Exception:  # noqa: BLE001
        return None


def avaliar(ticker: str, meta_yield: float) -> Avaliacao:
    """Avaliação de um ticker à meta de yield do usuário. Cacheada por ~6h."""
    _garantir_registro()
    tk = ticker.upper().strip()

    chave = (tk, round(meta_yield, 4))
    agora = time.time()
    if (ent := _cache.get(chave)) and agora - ent[0] < TTL_S:
        return ent[1]

    classe = ab.classificar(tk)
    impl = ab.para(classe)
    av = impl.avaliar(tk, _preco(tk), meta_yield)

    _cache[chave] = (agora, av)
    return av
