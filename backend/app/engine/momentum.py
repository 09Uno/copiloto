"""Momentum 12-1 (SPEC §13). Módulo puro.

**Hipótese declarada ANTES de rodar** (Jegadeesh & Titman, 1993): papéis que mais subiram nos
últimos 12 meses continuam subindo nos meses seguintes. É a anomalia mais robusta e mais
replicada de finanças — sobrevive em décadas de dados e em dezenas de países.

É o **oposto** da reversão: compra quem subiu, não quem caiu.

Três decisões que decidem se o teste é válido, e que quase todo mundo erra:

1. **PULA o mês mais recente** (o "-1" do 12-1). É exatamente ali que mora a reversão de curto
   prazo — a mesma que testamos e que não tem borda. Sem o gap, as duas anomalias se cancelam
   dentro do ranking e o teste não mede coisa nenhuma.

2. **Stop LARGO.** A tese precisa de meses para se realizar. Um stop apertado expulsa a posição
   no primeiro tropeço — foi o que estrangulou o cross-sectional (1.096 stops contra 248 alvos).

3. **Saída por TEMPO, não por alvo.** Momentum não tem alvo de preço: você segura enquanto a
   tendência dura. Pôr um take profit seria cortar justamente o que a estratégia vive de colher.

Aviso conhecido: momentum sofre **crashes** (2009 foi devastador para ela). Um drawdown enorme
no backtest não é bug — é a natureza da estratégia.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.core.config import Params
from app.engine.signals import AlertType

STRATEGY = "MOM"


def rank_universo(
    painel: pd.DataFrame,
    data: pd.Timestamp,
    membros: list[str],
    p: Params,
) -> pd.DataFrame:
    """Rankeia pelo retorno de formação (12 meses, PULANDO o mês mais recente).

    Só olha dados até `data` — o ranking não pode enxergar o futuro.
    """
    m = p.momentum
    necessario = m.janela_formacao + m.gap + 1

    hist = painel[(painel["timestamp"] <= data) & (painel["ticker"].isin(membros))]
    if hist.empty:
        return pd.DataFrame()

    linhas = []
    for tk, g in hist.groupby("ticker"):
        g = g.sort_values("timestamp")
        if len(g) < necessario:
            continue
        c = g["close"].to_numpy(dtype=float)

        # Janela de formação: de (janela+gap) atrás até (gap) atrás.
        # O trecho final — o último mês — fica DE FORA de propósito.
        p_ini = c[-(m.janela_formacao + m.gap)]
        p_fim = c[-(m.gap + 1)]
        if p_ini <= 0 or p_fim <= 0:
            continue

        linhas.append(
            {
                "ticker": tk,
                "retorno_formacao": float(np.log(p_fim / p_ini)),
                "close": float(c[-1]),
            }
        )

    r = pd.DataFrame(linhas)
    if len(r) < m.min_universo:
        return pd.DataFrame()

    # Relativo ao pelotão, como no cross-sectional: mediana, não média.
    r["excesso"] = r["retorno_formacao"] - r["retorno_formacao"].median()
    disp = r["excesso"].std(ddof=0)
    r["z"] = r["excesso"] / disp if disp > 0 else 0.0

    return r.sort_values("excesso").reset_index(drop=True)


def generate(
    ranking: pd.DataFrame,
    atr_por_ticker: dict[str, float],
    data: pd.Timestamp,
    p: Params,
    custo_ida_volta_pct: float,
) -> pd.DataFrame:
    """Compra os VENCEDORES, vende os PERDEDORES. (No cross-sectional era o contrário.)"""
    if ranking.empty:
        return _vazio()

    m = p.momentum
    n = min(m.n_extremos, len(ranking) // 3)
    if n == 0:
        return _vazio()

    vencedores = ranking.tail(n).assign(alert_type=AlertType.BUY.value)   # os que mais subiram
    perdedores = ranking.head(n).assign(alert_type=AlertType.SELL.value)  # os que mais caíram

    # Pessoa física não aluga e shorteia 15 papéis da B3 todo mês. Testar a perna vendida é
    # testar uma operação que nunca seria executada — e é ela que produz os crashes do momentum.
    alvos = vencedores if m.long_only else pd.concat([vencedores, perdedores])

    linhas = []
    for _, r in alvos.iterrows():
        atr = atr_por_ticker.get(r["ticker"])
        if not atr or atr <= 0 or r["close"] <= 0:
            continue

        sinal = 1.0 if r["alert_type"] == AlertType.BUY.value else -1.0
        trigger = float(r["close"])
        stop = trigger - sinal * m.stop_atr_mult * atr
        if stop <= 0:
            continue

        # SEM alvo de preço. A saída é a barreira de TEMPO (m.holding). O "take profit" existe
        # só porque a maquinaria de barreira exige um número — e é posto tão longe que nunca
        # é tocado. Cortar o vencedor cedo seria matar a estratégia.
        alvo = trigger + sinal * (trigger * 10.0)

        linhas.append(
            {
                "timestamp": data,
                "ticker": r["ticker"],
                "strategy": STRATEGY,
                "alert_type": r["alert_type"],
                "trigger_price": trigger,
                "stop_loss_price": stop,
                "take_profit_price": alvo,
                "retorno_formacao": float(r["retorno_formacao"]),
                "z": float(r["z"]),
                "atr": float(atr),
                "calculated_score": int(round(100 * float(np.tanh(abs(r["z"]) / 2.0)))),
                "engine_version": p.engine_version,
                "custo_ida_volta_pct": custo_ida_volta_pct,
            }
        )

    return pd.DataFrame(linhas) if linhas else _vazio()


def _vazio() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "timestamp", "ticker", "strategy", "alert_type", "trigger_price",
            "stop_loss_price", "take_profit_price", "retorno_formacao", "z", "atr",
            "calculated_score", "engine_version", "custo_ida_volta_pct",
        ]
    )
