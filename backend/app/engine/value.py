"""Avaliação fundamentalista — "esta ação está barata para CARREGAR?" (SPEC §12).

Pergunta diferente da do resto do motor. A reversão pergunta "vai repicar em 10 pregões?";
esta pergunta é sobre anos. Por isso é um módulo separado, com `strategy = 'VALUE'`: misturar
os dois datasets faria o ML treinar em maçãs com laranjas.

**Sem machine learning.** É aritmética contábil, e isso é uma virtude: cada número aqui pode ser
conferido à mão, o que é exatamente o que se quer quando a decisão é imobilizar capital por anos.

Nada aqui é conselho de compra. É uma triagem: aponta o que merece leitura do balanço.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from app.ingest.fundamentals import Fundamentos

STRATEGY = "VALUE"


@dataclass(frozen=True)
class Avaliacao:
    ticker: str
    preco: float
    graham: float | None          # valor intrínseco de Graham
    gordon: float | None          # valor por perpetuidade de dividendos
    margem_graham: float | None   # desconto (%) do preço contra Graham
    pl: float | None
    pvp: float | None
    pl_mediana_hist: float | None # o múltiplo do PRÓPRIO papel, historicamente
    desconto_vs_historia: float | None
    score: int
    alertas: tuple[str, ...]      # por que NÃO confiar cegamente


def graham(lpa: float, vpa: float) -> float | None:
    """√(22.5 × LPA × VPA) — o "número de Graham".

    22.5 = 15 (P/L máximo) × 1.5 (P/VP máximo). Só faz sentido com lucro E patrimônio
    positivos: raiz de número negativo não é "empresa barata", é empresa que dá prejuízo.
    """
    if lpa <= 0 or vpa <= 0:
        return None
    return float(np.sqrt(22.5 * lpa * vpa))


def gordon(dividendo_por_acao: float, taxa_desconto: float, crescimento: float) -> float | None:
    """D / (k − g) — perpetuidade de dividendos.

    Explode quando g se aproxima de k. Um modelo que devolve "valor infinito" porque alguém
    supôs crescimento eterno de 9% com desconto de 10% não é um modelo, é uma divisão por
    quase-zero. Exigimos folga.
    """
    if dividendo_por_acao <= 0 or taxa_desconto - crescimento < 0.02:
        return None
    return float(dividendo_por_acao / (taxa_desconto - crescimento))


def pl_historico(precos: pd.Series, lpa: float) -> float | None:
    """Mediana do P/L do PRÓPRIO papel ao longo do histórico.

    Comparar o P/L da Vale com o do Itaú não diz nada — setores têm múltiplos estruturalmente
    diferentes. Comparar o P/L da Vale de hoje com a mediana da Vale de 10 anos diz muito.

    Aproximação declarada: usa o LPA de hoje sobre os preços passados, porque não temos
    histórico point-in-time de lucro. Serve para ordem de grandeza, não para precisão.
    """
    if lpa <= 0 or precos.empty:
        return None
    return float((precos / lpa).median())


def avaliar(
    f: Fundamentos,
    precos_hist: pd.Series | None = None,
    taxa_desconto: float = 0.12,   # ~custo de capital em BRL
    crescimento: float = 0.03,
) -> Avaliacao | None:
    if not f.completo:
        return None

    alertas: list[str] = []
    g = graham(f.lpa, f.vpa)

    if f.lpa <= 0:
        alertas.append("prejuízo: LPA negativo — modelo clássico não se aplica")
    if f.vpa <= 0:
        alertas.append("patrimônio líquido negativo")
    if f.payout and f.payout > 1.0:
        alertas.append(f"payout de {f.payout:.0%}: distribui mais do que lucra")
    if f.pl and f.pl < 0:
        alertas.append("P/L negativo")
    if f.pl and f.pl > 0 and f.pl < 4:
        alertas.append(f"P/L de {f.pl:.1f} é baixo demais — desconfie do lucro (não-recorrente?)")

    div_acao = (f.dividendo_yield or 0) * f.preco
    gor = gordon(div_acao, taxa_desconto, crescimento) if div_acao > 0 else None

    margem = 100 * (g - f.preco) / f.preco if g else None

    pl_hist = pl_historico(precos_hist, f.lpa) if precos_hist is not None else None
    desconto_hist = (
        100 * (pl_hist - f.pl) / pl_hist if (pl_hist and f.pl and f.pl > 0) else None
    )

    return Avaliacao(
        ticker=f.ticker,
        preco=f.preco,
        graham=g,
        gordon=gor,
        margem_graham=margem,
        pl=f.pl,
        pvp=f.pvp,
        pl_mediana_hist=pl_hist,
        desconto_vs_historia=desconto_hist,
        score=_score(margem, desconto_hist, f.roe, alertas),
        alertas=tuple(alertas),
    )


def _score(
    margem: float | None,
    desconto_hist: float | None,
    roe: float | None,
    alertas: list[str],
) -> int:
    """0-100. Barato E bom — barato e ruim é armadilha de valor.

    Uma empresa pode estar 60% abaixo de Graham porque o lucro vai evaporar. Por isso o ROE
    entra: desconto sem qualidade não é oportunidade, é aviso. E cada alerta contábil derruba
    o score — o modelo não deve fingir convicção onde o balanço está estranho.
    """
    partes = []

    if margem is not None:  # desconto contra o valor intrínseco
        partes.append(45 * float(np.clip(margem / 50.0, 0, 1)))
    if desconto_hist is not None:  # barato contra a PRÓPRIA história
        partes.append(30 * float(np.clip(desconto_hist / 40.0, 0, 1)))
    if roe is not None:  # qualidade: o antídoto da armadilha de valor
        partes.append(25 * float(np.clip(roe / 0.20, 0, 1)))

    if not partes:
        return 0

    bruto = sum(partes) * (100.0 / 100.0)
    bruto *= max(0.0, 1.0 - 0.25 * len(alertas))  # cada alerta contábil corrói a convicção
    return int(round(float(np.clip(bruto, 0, 100))))
