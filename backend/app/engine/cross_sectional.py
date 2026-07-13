"""Reversão CROSS-SECTIONAL (SPEC §11). Módulo puro.

A reversão do `signals.py` é *absoluta*: espera cada papel cruzar ±2σ da própria média. Em
ação diária isso quase nunca acontece — e é uma borda historicamente fraca.

O que de fato funciona em ações é *relativo*: **rankear o universo inteiro e operar os
extremos**. Não importa se a VALE caiu 4%; importa se ela caiu 4% num dia em que o resto da
bolsa caiu 1%. O excesso de queda é que reverte.

Duas diferenças que fazem toda a diferença:

1. **Neutraliza o mercado.** Subtrai-se a mediana do universo. Sem isso, num crash geral a
   estratégia compraria 10 papéis de uma vez — comprando o índice, não a distorção — e o
   "sinal" seria só beta disfarçado.

2. **Sempre há sinal.** Um ranking sempre tem um último colocado. É por isso que ela resolve
   a fome de amostra do diário: 20 sinais por rebalanceamento, contra os ~2/ano por papel da
   reversão absoluta.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.core.config import Params
from app.engine.signals import AlertType

STRATEGY = "XSECT"


def rank_universo(
    painel: pd.DataFrame,
    data: pd.Timestamp,
    membros: list[str],
    p: Params,
) -> pd.DataFrame:
    """Rankeia os membros pelo retorno EXCEDENTE dos últimos N pregões.

    `painel` = OHLCV longo (ticker, timestamp, open/high/low/close/volume).
    Só olha para dados até `data` — o ranking não pode enxergar o futuro.
    """
    cs = p.cross_sectional
    hist = painel[(painel["timestamp"] <= data) & (painel["ticker"].isin(membros))]
    if hist.empty:
        return pd.DataFrame()

    linhas = []
    for tk, g in hist.groupby("ticker"):
        g = g.sort_values("timestamp")
        if len(g) < cs.janela_reversao + 1:
            continue
        c = g["close"].to_numpy(dtype=float)
        if c[-1] <= 0 or c[-1 - cs.janela_reversao] <= 0:
            continue
        linhas.append(
            {
                "ticker": tk,
                "retorno": float(np.log(c[-1] / c[-1 - cs.janela_reversao])),
                "close": float(c[-1]),
                "high": float(g["high"].iloc[-1]),
                "low": float(g["low"].iloc[-1]),
            }
        )

    r = pd.DataFrame(linhas)
    if len(r) < cs.min_universo:
        return pd.DataFrame()  # ranking com poucos papéis não significa nada

    # NEUTRALIZAÇÃO: mediana, não média — um papel que caiu 60% não pode arrastar a referência.
    r["excesso"] = r["retorno"] - r["retorno"].median()

    # Padroniza para virar score comparável entre datas (dias calmos e dias de pânico).
    disp = r["excesso"].std(ddof=0)
    r["z"] = r["excesso"] / disp if disp > 0 else 0.0
    r["rank"] = r["excesso"].rank(method="first")

    return r.sort_values("excesso").reset_index(drop=True)


def generate(
    ranking: pd.DataFrame,
    atr_por_ticker: dict[str, float],
    data: pd.Timestamp,
    p: Params,
    custo_ida_volta_pct: float,
) -> pd.DataFrame:
    """Os N mais castigados viram COMPRA; os N mais esticados, VENDA.

    O alvo e o stop saem do ATR (e não da média móvel): aqui a tese não é "voltar para a
    própria média", é "voltar para o pelotão". O alvo é posto a 2× a distância do stop, de
    modo que o R:R mínimo do SPEC §4 valha **por construção** — nada a descartar depois.
    """
    if ranking.empty:
        return _vazio()

    cs = p.cross_sectional
    n = min(cs.n_extremos, len(ranking) // 3)  # nunca operar mais de 1/3 do universo
    if n == 0:
        return _vazio()

    compras = ranking.head(n).assign(alert_type=AlertType.BUY.value)
    vendas = ranking.tail(n).assign(alert_type=AlertType.SELL.value)

    linhas = []
    for _, r in pd.concat([compras, vendas]).iterrows():
        atr = atr_por_ticker.get(r["ticker"])
        if not atr or atr <= 0 or r["close"] <= 0:
            continue

        sinal = 1.0 if r["alert_type"] == AlertType.BUY.value else -1.0
        risco = p.risco.stop_atr_mult * atr
        trigger = float(r["close"])

        stop = trigger - sinal * risco
        alvo = trigger + sinal * risco * p.risco.rr_minimo  # R:R garantido por construção

        if stop <= 0 or alvo <= 0:
            continue

        linhas.append(
            {
                "timestamp": data,
                "ticker": r["ticker"],
                "strategy": STRATEGY,
                "alert_type": r["alert_type"],
                "trigger_price": trigger,
                "stop_loss_price": stop,
                "take_profit_price": alvo,
                "rr": p.risco.rr_minimo,
                "excesso": float(r["excesso"]),
                "z": float(r["z"]),
                "atr": float(atr),
                "calculated_score": _score(float(r["z"]), p),
                "engine_version": p.engine_version,
                "custo_ida_volta_pct": custo_ida_volta_pct,
            }
        )

    return pd.DataFrame(linhas) if linhas else _vazio()


def _score(z: float, p: Params) -> int:
    """Quão extremo o papel está no ranking. |z| grande = mais destoante do pelotão.

    `tanh` de novo: sair de 2 para 3 desvios importa; de 6 para 7, quase nada.
    """
    return int(round(100 * float(np.tanh(abs(z) / 2.0))))


def _vazio() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "timestamp", "ticker", "strategy", "alert_type", "trigger_price",
            "stop_loss_price", "take_profit_price", "rr", "excesso", "z", "atr",
            "calculated_score", "engine_version", "custo_ida_volta_pct",
        ]
    )
