"""Métricas do backtest. Todas LÍQUIDAS de custos — nenhuma outra vale a pena olhar.

A métrica que decide o projeto é a **expectância**: quanto, em média, cada operação devolve.
Taxa de acerto é a métrica preferida de quem se engana: dá para acertar 80% das vezes e quebrar,
se os 20% restantes perderem 5× o que os 80% ganham.

Tudo é medido em **múltiplos de R** (R = o risco assumido na operação). Um trade que devolve
+2R devolveu o dobro do que arriscou. É o que torna comparável um trade de BTC e um de ITUB4.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class Metricas:
    n: int
    periodo: str
    anos: float

    taxa_acerto: float        # % de trades com R > 0
    expectancia_r: float      # ← A MÉTRICA. R médio por operação, líquida de custos.
    profit_factor: float      # soma dos ganhos / soma das perdas
    ganho_medio_r: float
    perda_media_r: float

    retorno_total_pct: float  # equity com risco fixo de 1% por operação
    cagr_pct: float
    max_drawdown_pct: float
    sharpe: float

    t_stat: float             # expectância / erro-padrão. Sem isto, ruído vira "borda".

    buy_hold_pct: float | None
    buy_hold_cagr_pct: float | None

    tp: int
    sl: int
    timeout: int

    @property
    def significante(self) -> bool:
        """|t| > 2 ≈ 95% de confiança de que a expectância não é zero.

        Sem este teste, "expectância positiva" não quer dizer nada. Com 262 trades e +0.065R,
        o erro-padrão é ±0.074R — o resultado é indistinguível de ZERO, e chamar isso de borda
        é confundir sorte com estratégia. É o erro que faz gente operar ruído com dinheiro real.
        """
        return abs(self.t_stat) > 2.0

    @property
    def bate_buy_hold(self) -> bool:
        """Ganhar 3% a.a. numa janela em que segurar o ativo deu 100% a.a. não é vitória.

        A estratégia não compete contra zero — compete contra a alternativa trivial de comprar
        e não fazer nada.
        """
        if self.buy_hold_cagr_pct is None:
            return True  # sem referência, não se pode reprovar por isto
        return self.cagr_pct > self.buy_hold_cagr_pct

    @property
    def tem_borda(self) -> bool:
        """O critério de saída da Fase 2, e ele é deliberadamente duro:
        expectância positiva, profit factor > 1 E estatisticamente significante.
        """
        return self.expectancia_r > 0 and self.profit_factor > 1.0 and self.significante


def _drawdown(equity: np.ndarray) -> float:
    pico = np.maximum.accumulate(equity)
    return float(((equity - pico) / pico).min() * 100.0)


def compute(
    trades: pd.DataFrame,
    risco_por_trade_pct: float = 1.0,
    buy_hold_pct: float | None = None,
    anos_periodo: float | None = None,
) -> Metricas | None:
    if trades.empty:
        return None

    r = trades["r_multiple"].to_numpy(dtype=float)
    ganhos, perdas = r[r > 0], r[r <= 0]

    ini, fim = trades["entrada_em"].min(), trades["saida_em"].max()
    anos = anos_periodo or max((fim - ini).days / 365.25, 1e-9)

    # Equity com RISCO FIXO por operação (SPEC §8.2): cada trade arrisca 1% da banca, e
    # devolve `r` vezes isso. É o sizing que o sistema de fato recomenda — usar retorno
    # percentual cru do preço mediria uma estratégia que ninguém opera.
    fator = 1.0 + (risco_por_trade_pct / 100.0) * r
    fator = np.maximum(fator, 0.01)  # ruína não vira número negativo
    equity = np.cumprod(fator)

    final = float(np.clip(equity[-1], 1e-9, 1e12))
    retorno_total = float((final - 1.0) * 100.0)
    # Via log, e não `final ** (1/anos)`: com período curto o expoente explode e a potência
    # estoura em OverflowError. Anualizar um resultado de poucos dias não faz sentido de
    # qualquer forma — daí o piso de um mês.
    lg = np.log(final) / max(anos, 1 / 12)
    cagr = float((np.exp(np.clip(lg, -50, 50)) - 1) * 100.0)

    # Sharpe por operação, anualizado pela frequência de trades. É uma aproximação —
    # o Sharpe "de verdade" pede curva diária — e está declarada como tal.
    trades_ano = len(r) / anos
    sharpe = (
        float(r.mean() / r.std(ddof=1) * np.sqrt(trades_ano))
        if len(r) > 1 and r.std(ddof=1) > 0
        else 0.0
    )

    soma_perdas = float(-perdas.sum())

    # Erro-padrão da expectância. É o que separa borda de sorte.
    sd = float(r.std(ddof=1)) if len(r) > 1 else 0.0
    erro_padrao = sd / np.sqrt(len(r)) if sd > 0 else 0.0
    t_stat = float(r.mean() / erro_padrao) if erro_padrao > 0 else 0.0

    return Metricas(
        n=len(r),
        periodo=f"{ini:%Y-%m} → {fim:%Y-%m}",
        anos=anos,
        taxa_acerto=100.0 * len(ganhos) / len(r),
        expectancia_r=float(r.mean()),
        profit_factor=float(ganhos.sum() / soma_perdas) if soma_perdas > 0 else float("inf"),
        ganho_medio_r=float(ganhos.mean()) if len(ganhos) else 0.0,
        perda_media_r=float(perdas.mean()) if len(perdas) else 0.0,
        retorno_total_pct=retorno_total,
        cagr_pct=cagr,
        max_drawdown_pct=_drawdown(equity),
        sharpe=sharpe,
        t_stat=t_stat,
        buy_hold_pct=buy_hold_pct,
        buy_hold_cagr_pct=(
            float(
                (
                    np.exp(
                        np.clip(np.log1p(buy_hold_pct / 100) / max(anos, 1 / 12), -50, 50)
                    )
                    - 1
                )
                * 100
            )
            if buy_hold_pct is not None and buy_hold_pct > -100
            else None
        ),
        tp=int((trades["outcome"] == "TP").sum()),
        sl=int((trades["outcome"] == "SL").sum()),
        timeout=int((trades["outcome"] == "TIMEOUT").sum()),
    )


def buy_and_hold(df: pd.DataFrame) -> float:
    """Retorno de simplesmente comprar e segurar. É contra ISTO que a estratégia compete —
    se ela não bate o buy & hold, ela é trabalho e risco em troca de nada."""
    if df.empty or len(df) < 2:
        return 0.0
    a, b = float(df["close"].iloc[0]), float(df["close"].iloc[-1])
    return (b / a - 1) * 100.0 if a > 0 else 0.0
