"""Regra de sinal, risco e score (SPEC §3-§4). Módulo puro.

Determinístico e explicável de propósito: nenhum ML aqui. Este é o BASELINE que o modelo da
Fase 6 vai ter que bater fora da amostra para justificar existir. Sem baseline honesto, não há
como saber se o ML acrescentou alguma coisa ou só ficou bonito.
"""

from __future__ import annotations

from enum import StrEnum

import numpy as np
import pandas as pd

from app.core.config import Market, Params
from app.engine.regime import MarketRegime


class AlertType(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


def _score(
    excesso_sigma: pd.Series,
    excesso_vol: pd.Series,
    excesso_rr: pd.Series,
    r2: pd.Series,
    p: Params,
) -> pd.Series:
    """Score 0-100: quanto o setup foi ALÉM do mínimo exigido em cada eixo.

    Um sinal que passa raspando em tudo tira ~0; um que supera folgadamente todos os limiares
    tira ~100. Os pesos são fixos e legíveis (params.yaml → score:) — o objetivo é poder olhar
    o número e saber de onde ele veio.

    `tanh` comprime o excesso: ir de 2σ para 3σ importa muito, de 6σ para 7σ quase nada.
    Sem isso, um outlier absurdo saturaria o score sozinho e esconderia os outros eixos.
    """
    s = p.score
    nitidez_lateral = 1.0 - (r2 / p.regime.r2_max_lateral).clip(0, 1)

    bruto = (
        s.peso_desvio * np.tanh(excesso_sigma)
        + s.peso_volume * np.tanh(excesso_vol)
        + s.peso_rr * np.tanh(excesso_rr)
        + s.peso_regime * nitidez_lateral
    )
    return (100.0 * bruto / s.total).round().clip(0, 100)


def generate(df: pd.DataFrame, p: Params, market: Market) -> pd.DataFrame:
    """Avalia a regra em cada vela. Devolve SÓ as velas que viraram sinal.

    Exige as colunas de `indicators.compute` + `market_regime` de `regime.classify`.
    Cada linha do resultado é um alerta candidato, com trigger/TP/SL/score/state_vector.
    """
    d = df.dropna(subset=["deviation_from_mean", "volume_z_score", "atr", "mu", "market_regime"])
    if d.empty:
        return _vazio()

    # --- §3: as três condições cumulativas
    lateral = d["market_regime"] == MarketRegime.LATERAL.value
    volume_ok = d["volume_z_score"] >= p.volume.z_minimo

    compra = lateral & volume_ok & (d["deviation_from_mean"] <= -p.bandas.n_sigma_entrada)
    venda = lateral & volume_ok & (d["deviation_from_mean"] >= p.bandas.n_sigma_entrada)

    d = d[compra | venda].copy()
    if d.empty:
        return _vazio()

    d["alert_type"] = np.where(
        d["deviation_from_mean"] <= 0, AlertType.BUY.value, AlertType.SELL.value
    )
    sinal = np.where(d["alert_type"] == AlertType.BUY.value, 1.0, -1.0)

    # --- §4: risco. O stop vem do ATR; o alvo é μ (a média das bandas, NÃO a reta de regressão
    # — a entrada é medida contra μ, então o alvo coerente é μ).
    d["trigger_price"] = d["close"]
    d["stop_loss_price"] = d["trigger_price"] - sinal * p.risco.stop_atr_mult * d["atr"]
    d["take_profit_price"] = d["mu"]

    risco = (d["trigger_price"] - d["stop_loss_price"]).abs()
    retorno = (d["take_profit_price"] - d["trigger_price"]).abs()

    # Alvo do lado ERRADO: numa compra, μ já abaixo do gatilho (média caindo rápido).
    # Não há alvo de reversão acima da entrada → o sinal não existe. Não se "ajusta" o alvo.
    alvo_valido = (sinal * (d["take_profit_price"] - d["trigger_price"])) > 0

    with np.errstate(divide="ignore", invalid="ignore"):
        rr = np.where(risco > 0, retorno / risco, 0.0)
    d["rr"] = rr

    # --- Filtro de R:R: critério de DESCARTE, não uma promessa (SPEC §4).
    # É aqui que morre a contradição do documento original, que exigia 1:2 e prescrevia
    # níveis que davam 1.67:1 — o sistema descartaria todos os próprios sinais.
    d = d[alvo_valido & (d["rr"] >= p.risco.rr_minimo)].copy()
    if d.empty:
        return _vazio()

    # --- Score (0-100)
    d["calculated_score"] = _score(
        excesso_sigma=d["deviation_from_mean"].abs() - p.bandas.n_sigma_entrada,
        excesso_vol=d["volume_z_score"] - p.volume.z_minimo,
        excesso_rr=d["rr"] - p.risco.rr_minimo,
        r2=d["regression_r2"],
        p=p,
    ).astype(int)

    # --- state_vector (SPEC §9): as 5 features adimensionais, para a analogia histórica.
    d["state_vector"] = [
        [float(v) for v in row]
        for row in d[
            [
                "regression_slope",
                "regression_r2",
                "deviation_from_mean",
                "volume_z_score",
                "atr_pct",
            ]
        ].to_numpy()
    ]

    d["engine_version"] = p.engine_version
    d["custo_ida_volta_pct"] = p.custos.ida_e_volta(market)

    return d[
        [
            "close",
            "regression_slope",
            "regression_r2",
            "deviation_from_mean",
            "volume_z_score",
            "atr",
            "atr_pct",
            "mu",
            "market_regime",
            "alert_type",
            "trigger_price",
            "take_profit_price",
            "stop_loss_price",
            "rr",
            "calculated_score",
            "state_vector",
            "engine_version",
            "custo_ida_volta_pct",
        ]
    ]


def size_position(banca: float, risco_pct: float, trigger: float, stop: float) -> float:
    """Quantidade a comprar, por risco fixo (SPEC §8.2).

    É o que dá sentido ao stop: sem sizing, ele é decorativo. A perda máxima da operação passa
    a ser `banca × risco_pct` INDEPENDENTE do ativo — é o stop mais largo que compra menos, não
    o palpite de quanto "dá pra arriscar".
    """
    distancia = abs(trigger - stop)
    if distancia <= 0:
        return 0.0
    return (banca * risco_pct / 100.0) / distancia


def _vazio() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "close", "regression_slope", "regression_r2", "deviation_from_mean",
            "volume_z_score", "atr", "atr_pct", "mu", "market_regime", "alert_type",
            "trigger_price", "take_profit_price", "stop_loss_price", "rr",
            "calculated_score", "state_vector", "engine_version", "custo_ida_volta_pct",
        ]
    )
