"""Triple barrier (SPEC §5). Módulo puro.

Rotula o desfecho de um sinal com TRÊS barreiras: alvo, stop e um HORIZONTE MÁXIMO. A terceira
é a que o plano original esquecia — sem ela, um sinal que nunca toca alvo nem stop fica órfão,
o rótulo vira NULL e some do dataset de treino. Some justamente a categoria mais informativa:
"o setup não deu em nada".

Dois cuidados que decidem se o backtest é honesto ou ficção:

1. A avaliação começa na vela SEGUINTE à do sinal. Usar a própria vela do gatilho é lookahead:
   no momento em que ela fechou, você não sabia o máximo/mínimo que ela ia fazer.

2. Quando alvo e stop caem DENTRO DA MESMA VELA, o OHLC não diz qual veio primeiro. Assumimos
   o STOP (pior caso). Errar para o pessimista mantém o histórico honesto; errar para o
   otimista fabrica uma borda que não existe — e é assim que backtests bonitos quebram no ar.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

import pandas as pd

from app.engine.signals import AlertType


class Outcome(StrEnum):
    TP = "TP"            # bateu o alvo
    SL = "SL"            # bateu o stop
    TIMEOUT = "TIMEOUT"  # expirou o horizonte: o retorno na saída É o rótulo, não NULL


@dataclass(frozen=True)
class BarrierResult:
    outcome: Outcome
    exit_price: float
    exit_index: int          # posição na série (não o timestamp)
    velas_ate_saida: int
    retorno_bruto_pct: float
    retorno_liquido_pct: float  # o que importa: já descontado o custo de ida e volta
    max_return_pct: float       # melhor ganho não realizado durante a operação


def evaluate(
    ohlc: pd.DataFrame,
    entry_pos: int,
    side: AlertType,
    trigger: float,
    take_profit: float,
    stop_loss: float,
    horizonte: int,
    custo_ida_volta_pct: float,
) -> BarrierResult | None:
    """Aplica as barreiras a partir de `entry_pos`. None = a série acabou antes do desfecho.

    `None` NÃO é TIMEOUT: um sinal perto da borda do histórico simplesmente ainda não tem
    desfecho observável. Rotulá-lo seria inventar dado.
    """
    n = len(ohlc)
    inicio = entry_pos + 1  # nunca a própria vela do sinal (cuidado 1)
    fim = min(inicio + horizonte, n)

    if inicio >= n:
        return None

    long = side is AlertType.BUY
    direcao = 1.0 if long else -1.0

    highs = ohlc["high"].to_numpy(dtype=float)
    lows = ohlc["low"].to_numpy(dtype=float)
    closes = ohlc["close"].to_numpy(dtype=float)

    melhor = trigger  # preço mais favorável visto até agora

    for i in range(inicio, fim):
        melhor = max(melhor, highs[i]) if long else min(melhor, lows[i])

        bateu_tp = highs[i] >= take_profit if long else lows[i] <= take_profit
        bateu_sl = lows[i] <= stop_loss if long else highs[i] >= stop_loss

        if bateu_tp or bateu_sl:
            # Ambos na mesma vela → pior caso (cuidado 2).
            eh_stop = bateu_sl
            preco = stop_loss if eh_stop else take_profit
            return _resultado(
                Outcome.SL if eh_stop else Outcome.TP,
                preco, i, i - entry_pos, trigger, melhor, direcao, custo_ida_volta_pct,
            )

    if fim < inicio + horizonte:
        return None  # histórico acabou antes de o horizonte fechar

    saida = fim - 1
    return _resultado(
        Outcome.TIMEOUT,
        closes[saida], saida, saida - entry_pos, trigger, melhor, direcao,
        custo_ida_volta_pct,
    )


def _resultado(
    outcome: Outcome,
    exit_price: float,
    exit_index: int,
    velas: int,
    trigger: float,
    melhor: float,
    direcao: float,
    custo_pct: float,
) -> BarrierResult:
    bruto = direcao * (exit_price - trigger) / trigger * 100.0
    maximo = direcao * (melhor - trigger) / trigger * 100.0
    return BarrierResult(
        outcome=outcome,
        exit_price=float(exit_price),
        exit_index=int(exit_index),
        velas_ate_saida=int(velas),
        retorno_bruto_pct=float(bruto),
        retorno_liquido_pct=float(bruto - custo_pct),
        max_return_pct=float(maximo),
    )
