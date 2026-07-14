"""Backtest de CARTEIRA — a forma em que a tese é de fato afirmada.

O backtest anterior testava momentum como operação individual com stop loss. **Isso não é o
que a academia afirma.** A tese original (Jegadeesh & Titman) é uma carteira: compra-se uma
cesta de vencedores, SEGURA-SE, rebalanceia todo mês. Sem stop.

E o stop importava: dos 843 trades, 291 foram estopados — expulsos por uma queda temporária,
exatamente o que uma carteira de longo prazo não faz. O mecanismo de risco pode ter matado a
estratégia que ele deveria proteger.

Aqui não há stop, não há alvo, não há R-multiple. Há uma carteira, uma curva de patrimônio, e
um índice para bater.

DUAS HONESTIDADES QUE MUDAM O RESULTADO:

1. **Benchmark justo.** O Ibovespa é índice de RETORNO TOTAL (reinveste dividendos); nossos
   preços do COTAHIST são ajustados por desdobramento mas NÃO por dividendo. Comparar direto
   seria injusto CONTRA nós. O benchmark principal é uma carteira igualmente ponderada de TODO
   o universo — mesma base de preço, mesmo custo, comparação maçã com maçã. O Ibovespa aparece
   à parte, com a ressalva.

2. **Custo de giro.** Trocar 5 das 15 posições todo mês custa dinheiro. Cada entrada e cada
   saída paga uma perna. Uma carteira que gira muito pode ter alfa bruto e prejuízo líquido.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from app.core import b3_universe
from app.core.config import Market, Params


@dataclass
class Curva:
    nome: str
    retornos: pd.Series      # retorno mensal, líquido de custo de giro
    equity: pd.Series

    @property
    def anos(self) -> float:
        return max(len(self.retornos) / 12.0, 1e-9)

    @property
    def cagr(self) -> float:
        f = float(self.equity.iloc[-1])
        return (np.exp(np.log(max(f, 1e-9)) / self.anos) - 1) * 100

    @property
    def vol(self) -> float:
        return float(self.retornos.std(ddof=1) * np.sqrt(12) * 100)

    @property
    def sharpe(self) -> float:
        s = self.retornos.std(ddof=1)
        return float(self.retornos.mean() / s * np.sqrt(12)) if s > 0 else 0.0

    @property
    def max_dd(self) -> float:
        e = self.equity.to_numpy()
        return float(((e - np.maximum.accumulate(e)) / np.maximum.accumulate(e)).min() * 100)


def _matriz_precos(painel: pd.DataFrame) -> pd.DataFrame:
    return painel.pivot_table(
        index="timestamp", columns="ticker", values="close", aggfunc="last"
    ).sort_index()


def _datas_rebalance(precos: pd.DataFrame) -> list[pd.Timestamp]:
    s = pd.Series(precos.index, index=precos.index)
    return list(s.resample("ME").last().dropna())


def _momentum_12_1(precos: pd.DataFrame, data: pd.Timestamp, p: Params) -> pd.Series:
    """Retorno de formação: 12 meses PULANDO o mês recente. Só olha o passado."""
    m = p.momentum
    hist = precos.loc[:data]
    if len(hist) < m.janela_formacao + m.gap + 1:
        return pd.Series(dtype=float)

    p_ini = hist.iloc[-(m.janela_formacao + m.gap)]
    p_fim = hist.iloc[-(m.gap + 1)]

    r = np.log(p_fim / p_ini)
    return r.replace([np.inf, -np.inf], np.nan).dropna()


def _custo_giro(anterior: set[str], atual: set[str], n: int, custo_perna: float) -> float:
    """Cada nome que entra e cada nome que sai paga uma perna, sobre o seu peso (1/n)."""
    if n == 0:
        return 0.0
    trocas = len(atual - anterior) + len(anterior - atual)
    return (trocas / n) * (custo_perna / 100.0)


def rodar(
    p: Params,
    market: Market = Market.B3,
    inicio: str = "2010-01-01",
) -> tuple[Curva, Curva]:
    """Devolve (carteira momentum, benchmark igualmente ponderado do universo)."""
    painel, comp = b3_universe.load()
    precos = _matriz_precos(painel)
    precos = precos.loc[precos.index >= pd.Timestamp(inicio, tz="UTC")]

    custo_perna = p.custos.por_perna(market)
    n_alvo = p.momentum.n_extremos
    datas = _datas_rebalance(precos)

    ret_mom, ret_bh, marcos = [], [], []
    carteira_ant: set[str] = set()
    universo_ant: set[str] = set()

    for i in range(len(datas) - 1):
        d, prox = datas[i], datas[i + 1]

        membros = [t for t in b3_universe.membros_em(comp, d) if t in precos.columns]
        if len(membros) < p.momentum.min_universo:
            continue

        rank = _momentum_12_1(precos[membros], d, p)
        if len(rank) < p.momentum.min_universo:
            continue

        carteira = set(rank.nlargest(n_alvo).index)
        universo = set(rank.index)

        # Retorno do mês seguinte, de fechamento a fechamento, igualmente ponderado.
        px_ini = precos.loc[d]
        px_fim = precos.loc[prox]

        def _retorno(nomes: set[str]) -> float:
            vivos = [t for t in nomes if pd.notna(px_ini.get(t)) and pd.notna(px_fim.get(t))]
            if not vivos:
                return 0.0
            return float(np.mean([px_fim[t] / px_ini[t] - 1.0 for t in vivos]))

        r_mom = _retorno(carteira) - _custo_giro(
            carteira_ant, carteira, n_alvo, custo_perna
        )
        r_bh = _retorno(universo) - _custo_giro(
            universo_ant, universo, len(universo), custo_perna
        )

        ret_mom.append(r_mom)
        ret_bh.append(r_bh)
        marcos.append(prox)

        carteira_ant, universo_ant = carteira, universo

    idx = pd.DatetimeIndex(marcos)
    s_mom = pd.Series(ret_mom, index=idx)
    s_bh = pd.Series(ret_bh, index=idx)

    return (
        Curva("Momentum (15 vencedores)", s_mom, (1 + s_mom).cumprod()),
        Curva("Universo igualmente ponderado", s_bh, (1 + s_bh).cumprod()),
    )


def fatiar(c: Curva, ate: pd.Timestamp) -> tuple[Curva, Curva]:
    """(dentro, fora) da amostra, por corte temporal."""
    d = c.retornos[c.retornos.index <= ate]
    f = c.retornos[c.retornos.index > ate]
    return (
        Curva(c.nome, d, (1 + d).cumprod()),
        Curva(c.nome, f, (1 + f).cumprod()),
    )
