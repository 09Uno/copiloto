"""Classe AÇÃO — teto por yield, pilares vindos do balanço da CVM.

**O preço teto é o critério ancorado no SEU objetivo:**

    teto = dividendo por ação ÷ meta de yield

Se a TAEE3 paga R$ 1,08 e sua meta é 8%, o teto é R$ 13,50. Acima disso, a ação **não entrega
o que você decidiu que quer**. Isso não prevê nada — não diz que ela vai cair. Diz que, a este
preço, o dividendo não te dá o retorno que você estabeleceu. A decisão vem de você.

E "euforia" vira número: euforia é pagar um múltiplo que você **nunca pagou antes**. O P/L e o
P/VP contra a **mediana histórica do próprio papel** medem isso (comparar o P/L da Vale com o
do Itaú não diz nada — setores têm múltiplos estruturalmente diferentes).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.ativos.base import Avaliacao, Classe, ClasseDeAtivo, Metrica, Teto
from app.engine import fundamentos as fd

JANELA_MULTIPLO_ANOS = 10  # o papel contra a PRÓPRIA história


class Acao(ClasseDeAtivo):
    classe = Classe.ACAO

    def __init__(self, painel_cvm: pd.DataFrame, mapa: pd.DataFrame,
                 precos: dict[str, pd.Series] | None = None) -> None:
        self._painel = painel_cvm
        self._mapa = mapa
        self._precos = precos or {}  # histórico de fechamento, para os múltiplos históricos
        self._cache_serie: dict[tuple[str, str], pd.Series | None] = {}

    def metricas_disponiveis(self) -> dict[str, str]:
        return {
            "lpa": "lucro por ação",
            "vpa": "valor patrimonial por ação",
            "dpa": "dividendo por ação (12m)",
            "roe": "retorno sobre o patrimônio",
            "payout": "% do lucro distribuído",
            "divida_ebit": "dívida líquida / EBIT",
            "margem": "margem líquida",
            "pl": "preço / lucro",
            "pvp": "preço / valor patrimonial",
            "dy": "dividend yield",
            "pl_vs_historia": "P/L vs. a mediana do próprio papel",
            "pvp_vs_historia": "P/VP vs. a mediana do próprio papel",
        }

    def avaliar(self, ticker: str, preco: float | None, meta_yield: float) -> Avaliacao:
        linha = self._mapa[self._mapa["ticker"] == ticker]
        if linha.empty:
            return Avaliacao(
                ticker=ticker, classe=self.classe, preco=preco, metricas={}, teto=None,
                sem_criterio="papel não encontrado no cadastro da CVM",
            )

        f = fd.calcular(
            self._painel[self._painel["cnpj"] == linha["cnpj"].iloc[0]],
            ticker, linha["empresa"].iloc[0],
        )
        if f is None:
            return Avaliacao(
                ticker=ticker, classe=self.classe, preco=preco, metricas={}, teto=None,
                sem_criterio="sem balanço publicado",
            )

        pl = preco / f.lpa if (preco and f.lpa and f.lpa > 0) else None
        pvp = preco / f.vpa if (preco and f.vpa and f.vpa > 0) else None
        dy = f.dpa / preco if (preco and f.dpa and preco > 0) else None

        cnpj = linha["cnpj"].iloc[0]
        pl_hist = self._mediana_historica(ticker, cnpj, "lpa")
        pvp_hist = self._mediana_historica(ticker, cnpj, "vpa")

        m = [
            Metrica("lpa", "LPA", f.lpa, "R$ {:.2f}"),
            Metrica("vpa", "VPA", f.vpa, "R$ {:.2f}"),
            Metrica("dpa", "DPA (12m)", f.dpa, "R$ {:.2f}"),
            Metrica("roe", "ROE", f.roe, "{:.1%}"),
            Metrica("payout", "Payout", f.payout, "{:.0%}", melhor_alto=False),
            Metrica("divida_ebit", "Dív.Líq/EBIT", f.divida_ebit, "{:.1f}x",
                    melhor_alto=False),
            Metrica("margem", "Margem", f.margem, "{:.1%}"),
            Metrica("pl", "P/L", pl, "{:.1f}", melhor_alto=False),
            Metrica("pvp", "P/VP", pvp, "{:.2f}", melhor_alto=False),
            Metrica("dy", "Dividend Yield", dy, "{:.2%}"),
            Metrica("pl_vs_historia", "P/L vs. história", _razao(pl, pl_hist), "{:.0%}",
                    melhor_alto=False),
            Metrica("pvp_vs_historia", "P/VP vs. história", _razao(pvp, pvp_hist), "{:.0%}",
                    melhor_alto=False),
        ]

        return Avaliacao(
            ticker=ticker, classe=self.classe, preco=preco,
            metricas={x.nome: x for x in m},
            teto=self._teto(f.dpa, meta_yield),
            alertas=_alertas(f, pl),
        )

    def _teto(self, dpa: float | None, meta_yield: float) -> Teto | None:
        """O critério. Sem dividendo não há teto de yield — e o sistema diz isso."""
        if not dpa or dpa <= 0 or meta_yield <= 0:
            return None
        return Teto(
            valor=dpa / meta_yield,
            criterio=f"dividendo R$ {dpa:.2f} ÷ meta {meta_yield:.0%}",
            meta=meta_yield,
        )

    def _mediana_historica(self, ticker: str, cnpj: str, metrica: str) -> float | None:
        """Mediana do múltiplo do PRÓPRIO papel, com o indicador POINT-IN-TIME de cada data.

        **A armadilha que quase passou:** usar o LPA de HOJE sobre os preços passados faz a
        conta colapsar. `P/L_hoje ÷ mediana(preços/LPA_hoje)` = `preço_hoje ÷ mediana(preços)` —
        o LPA some da equação, e o "múltiplo vs. história" vira **preço vs. preço**. Foi o que
        denunciou o P/L e o P/VP saírem com o MESMO 122% na TAEE3.

        E isso mentiria: se o lucro da empresa dobrou em 10 anos, o preço 22% acima da mediana
        pode significar que ela está **mais barata** em P/L, não mais cara. O detector de
        euforia diria o contrário do certo.

        O conserto exige saber o LPA que **estava público em cada data** — e é exatamente o que
        o `DT_RECEB` da CVM entrega. É para isso que a fundação point-in-time existe.
        """
        precos = self._precos.get(ticker)
        if precos is None or precos.empty:
            return None

        serie = self._por_acao_no_tempo(cnpj, ticker, metrica)
        if serie is None or serie.empty:
            return None

        # Para cada pregão, o indicador que estava PUBLICADO naquele dia.
        alinhado = serie.reindex(precos.index, method="ffill")
        multiplo = (precos / alinhado).replace([np.inf, -np.inf], np.nan).dropna()
        multiplo = multiplo[multiplo > 0]

        corte = precos.index.max() - pd.Timedelta(days=365 * JANELA_MULTIPLO_ANOS)
        janela = multiplo[multiplo.index >= corte]
        return float(janela.median()) if len(janela) > 60 else None

    def _por_acao_no_tempo(
        self, cnpj: str, ticker: str, metrica: str
    ) -> pd.Series | None:
        """LPA (ou VPA) trimestre a trimestre, indexado pela DATA DE PUBLICAÇÃO."""
        chave = (cnpj, metrica)
        if chave in self._cache_serie:
            return self._cache_serie[chave]

        painel = self._painel[self._painel["cnpj"] == cnpj]
        if painel.empty:
            self._cache_serie[chave] = None
            return None

        pontos: dict[pd.Timestamp, float] = {}
        for pub in sorted(painel["dt_receb"].dropna().unique()):
            f = fd.calcular(painel, ticker, "", ate=pd.Timestamp(pub))
            if f is None:
                continue
            v = f.lpa if metrica == "lpa" else f.vpa
            if v and v > 0:
                pontos[pd.Timestamp(pub)] = v

        s = pd.Series(pontos).sort_index() if pontos else None
        self._cache_serie[chave] = s
        return s


def _razao(atual: float | None, historico: float | None) -> float | None:
    """1.0 = está no múltiplo de sempre. 1.6 = está 60% mais caro que a própria história."""
    if atual is None or historico is None or historico <= 0:
        return None
    return atual / historico


def _alertas(f: fd.Fundamento, pl: float | None) -> tuple[str, ...]:
    a: list[str] = []

    if f.payout and f.payout > 1.0:
        a.append(
            f"payout de {f.payout:.0%}: distribui mais do que lucra — "
            "o dividendo está saindo de caixa ou de dívida, não do resultado"
        )
    if f.lucro_12m is not None and f.lucro_12m <= 0:
        a.append("prejuízo nos últimos 12 meses")
    if f.divida_ebit and f.divida_ebit > 3.5:
        a.append(f"dívida líquida em {f.divida_ebit:.1f}x o EBIT — alavancagem alta")
    if pl and 0 < pl < 4:
        a.append(f"P/L de {pl:.1f} é baixo demais — desconfie do lucro (não-recorrente?)")
    if f.roe is not None and f.roe < 0.05:
        a.append(f"ROE de {f.roe:.1%}: barato pode ser armadilha de valor, não oportunidade")

    return tuple(a)
