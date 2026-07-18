"""Classe FII — o P/VP é o rei, não o dividendo.

**A diferença que importa em relação à ação:** um FII é um fundo. Ele publica todo mês o
patrimônio contábil por cota. Comprar a 0,87× o patrimônio é objetivamente diferente de comprar
a 1,25× — e essa clareza não existe em ação (o "patrimônio" de uma empresa operacional não diz
quase nada sobre o valor dela; o de um fundo de imóveis diz muito).

Por isso o FII tem **dois** critérios, e não um:

  1. **Preço teto por rendimento** — igual à ação: `rendimento anual ÷ sua meta de yield`
  2. **P/VP** — pagar 1,25× o patrimônio significa que você compra R$ 1,00 de imóvel por R$ 1,25

Um FII pode estar dentro do teto de yield **e ainda assim caro** (o rendimento está alto porque
o fundo está distribuindo ganho de capital não-recorrente, e não aluguel). O P/VP denuncia.

**O que o sistema NÃO sabe: vacância.** Ela vive no relatório gerencial (FNET), que não é dado
estruturado. Vai aparecer na tela como "não disponível" — não como um número inventado.
"""

from __future__ import annotations

import pandas as pd

from app.ativos.base import Avaliacao, Classe, ClasseDeAtivo, Metrica, Teto


class FII(ClasseDeAtivo):
    classe = Classe.FII

    def __init__(
        self,
        painel: pd.DataFrame,
        rendimentos: dict[str, pd.Series] | None = None,
    ) -> None:
        self._painel = painel
        self._rend = rendimentos or {}  # yfinance: confiável para FII (distribuição simples)

    def metricas_disponiveis(self) -> dict[str, str]:
        return {
            "p_vp": "preço / valor patrimonial da cota",
            # `dpa` e `vpa` são os nomes CANÔNICOS (base.RENDA_POR_UNIDADE / VALOR_PATRIMONIAL).
            # O FII chama de "rendimento por cota" e a ação de "dividendo por ação" — mas ambos
            # registram sob o mesmo nome, e por isso o motor de decisão calcula yield-on-cost
            # para os dois sem saber qual é qual.
            "dpa": "rendimento por cota (12m)",
            "vpa": "valor patrimonial da cota",
            "dy": "dividend yield",
            "alavancagem": "passivo / patrimônio",
            "cotistas": "número de cotistas",
            "patrimonio": "patrimônio líquido",
            "perfil": "tijolo / papel / híbrido",
            # vacância NÃO entra: a CVM não publica, e o sistema não inventa.
        }

    def metricas_percentuais(self) -> set[str]:
        # dy e alavancagem são frações exibidas em % → 'dy>8' = 8%. p_vp é múltiplo (~0,9),
        # dpa/vpa/patrimonio são R$, cotistas é contagem: todos literais.
        return {"dy", "alavancagem"}

    def avaliar(self, ticker: str, preco: float | None, meta_yield: float) -> Avaliacao:
        d = self._painel[self._painel["ticker"] == ticker]
        if d.empty:
            return Avaliacao(
                ticker=ticker, classe=self.classe, preco=preco, metricas={}, teto=None,
                sem_criterio=(
                    "FII não mapeado no informe mensal da CVM. O ISIN nem sempre embute o "
                    "código do papel (o BTHF11 é BR0EI9CTF007) — este é um caso a cadastrar."
                ),
            )

        u = d.sort_values("dt_refer").iloc[-1]
        vp = _f(u.get("vp_cota"))
        pat = _f(u.get("patrimonio"))
        passivo = _f(u.get("passivo"))

        rend = self._rendimento_12m(ticker)
        p_vp = preco / vp if (preco and vp and vp > 0) else None
        dy = rend / preco if (rend and preco and preco > 0) else None
        alav = passivo / pat if (passivo and pat and pat > 0) else None

        m = [
            Metrica("p_vp", "P/VP", p_vp, "{:.2f}", melhor_alto=False),
            # Nomes canônicos (`dpa`, `vpa`) com rótulo de FII: o nome é a interface,
            # o rótulo é a tela.
            Metrica("dpa", "Rendimento (12m)", rend, "R$ {:.2f}"),
            Metrica("vpa", "VP da cota", vp, "R$ {:.2f}"),
            Metrica("dy", "Dividend Yield", dy, "{:.2%}"),
            Metrica("alavancagem", "Passivo / PL", alav, "{:.1%}", melhor_alto=False),
            Metrica("cotistas", "Cotistas", _f(u.get("cotistas")), "{:,.0f}"),
            Metrica("patrimonio", "Patrimônio", pat, "R$ {:,.0f}"),
        ]

        comp = _composicao(u)
        m += [
            Metrica("pct_imovel", "  em imóvel direto", comp.get("imovel"), "{:.0%}"),
            Metrica("pct_fii", "  em cotas de outros FIIs", comp.get("fii"), "{:.0%}"),
            Metrica("pct_papel", "  em papel (CRI/LCI)", comp.get("papel"), "{:.0%}"),
        ]

        return Avaliacao(
            ticker=ticker, classe=self.classe, preco=preco,
            metricas={x.nome: x for x in m},
            teto=_teto(rend, meta_yield),
            alertas=_alertas(p_vp, alav, dy, comp, u),
        )

    def _rendimento_12m(self, ticker: str) -> float | None:
        s = self._rend.get(ticker)
        if s is None or s.empty:
            return None
        corte = pd.Timestamp.now() - pd.Timedelta(days=365)
        ult = s[s.index >= corte]
        return float(ult.sum()) if len(ult) else None


def _f(v) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x else x  # NaN


def _teto(rendimento: float | None, meta: float) -> Teto | None:
    if not rendimento or rendimento <= 0 or meta <= 0:
        return None
    return Teto(
        valor=rendimento / meta,
        criterio=f"rendimento R$ {rendimento:.2f}/ano ÷ meta {meta:.0%}",
        meta=meta,
    )


def _composicao(u: pd.Series) -> dict[str, float]:
    """A composição REAL do ativo — fato, não interpretação.

    O campo "Segmento_Atuacao" da CVM vem "Multicategoria" para todo mundo e não serve para
    nada. Já a composição do ativo diz o que o fundo **de fato é** — e às vezes surpreende: a
    GARE11 se chama "FII Guardial LOGÍSTICA", mas 68% do ativo dela são **cotas de outros
    FIIs** e 15% é CRI. Quem compra achando que tem galpão logístico tem, na verdade, um fundo
    de fundos com uma perna de crédito.

    Mostramos os percentuais e deixamos VOCÊ interpretar. Um rótulo ("tijolo", "papel") seria
    uma opinião minha disfarçada de dado.
    """
    imo = _f(u.get("valor_imoveis")) or 0.0
    pap = _f(u.get("valor_papel")) or 0.0
    cotas = _f(u.get("valor_cotas_fii")) or 0.0
    total = imo + pap + cotas
    if total <= 0:
        return {}
    return {"imovel": imo / total, "papel": pap / total, "fii": cotas / total}


def _alertas(
    p_vp: float | None,
    alav: float | None,
    dy: float | None,
    comp: dict[str, float],
    u: pd.Series,
) -> tuple[str, ...]:
    a: list[str] = []

    if p_vp and p_vp > 1.15:
        a.append(
            f"P/VP de {p_vp:.2f}: você paga R$ {p_vp:.2f} por R$ 1,00 de patrimônio — "
            "um FII acima do valor patrimonial precisa de um motivo muito bom"
        )
    if p_vp and p_vp < 0.75:
        a.append(
            f"P/VP de {p_vp:.2f}: desconto grande. Ou é oportunidade, ou o mercado sabe algo "
            "sobre os imóveis que o balanço ainda não mostra (vacância, inadimplência)"
        )
    if alav and alav > 0.30:
        a.append(
            f"passivo em {alav:.0%} do patrimônio — FII alavancado sofre mais na alta de juros"
        )
    if dy and dy > 0.14:
        a.append(
            f"DY de {dy:.1%} é alto demais para aluguel: pode ser ganho de capital "
            "NÃO-RECORRENTE (venda de imóvel) disfarçado de renda"
        )

    if comp.get("fii", 0) > 0.5:
        a.append(
            f"{comp['fii']:.0%} do ativo são COTAS DE OUTROS FIIs — você paga duas camadas de "
            "taxa, e o P/VP aqui reflete o valor dos fundos-alvo, não de imóveis"
        )
    if comp.get("papel", 0) > 0.3:
        a.append(
            f"{comp['papel']:.0%} do ativo é PAPEL (CRI/LCI): o rendimento segue IPCA/CDI, não "
            "aluguel — e o risco é de CRÉDITO (inadimplência), não de vacância"
        )

    a.append(
        "vacância: não disponível (a CVM não publica; está no relatório gerencial do fundo)"
    )
    return tuple(a)
