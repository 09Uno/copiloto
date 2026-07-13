"""Testes do motor sobre séries SINTÉTICAS de comportamento conhecido.

Dado real não serve para testar isto: não se sabe qual é a resposta certa. Aqui a série é
construída para que a resposta seja óbvia, e o teste checa se o motor a encontra.

O teste mais importante do arquivo é `test_nao_opera_reversao_em_tendencia_forte`: é a regra
que impede o erro mais caro da estratégia — comprar o rompimento de −2σ no meio de uma queda
organizada, que não é exaustão, é continuação.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.core.config import Market, load_params
from app.engine import indicators, regime, signals
from app.engine.barriers import Outcome, evaluate
from app.engine.regime import MarketRegime
from app.engine.signals import AlertType

P = load_params()


def _ohlcv(closes, volumes=None, spread=0.005) -> pd.DataFrame:
    closes = np.asarray(closes, dtype=float)
    n = len(closes)
    vol = np.full(n, 1000.0) if volumes is None else np.asarray(volumes, dtype=float)
    return pd.DataFrame(
        {
            "timestamp": pd.date_range("2024-01-01", periods=n, freq="1D", tz="UTC"),
            "open": closes,
            "high": closes * (1 + spread),
            "low": closes * (1 - spread),
            "close": closes,
            "volume": vol,
        }
    )


def _com_regime(df):
    f = indicators.compute(df, P)
    f["market_regime"] = regime.classify(f, P)
    return f


# --------------------------------------------------------------- indicadores


def test_slope_de_tendencia_exponencial_e_o_retorno_log_por_periodo():
    # Preço crescendo 1%/dia: em log-preço isso é uma RETA de inclinação ln(1.01).
    # É exatamente por isso que a regressão roda em log (SPEC §2.1).
    closes = 100 * 1.01 ** np.arange(300)
    f = indicators.compute(_ohlcv(closes), P)

    assert f["regression_slope"].iloc[-1] == pytest.approx(np.log(1.01), rel=1e-6)
    assert f["regression_r2"].iloc[-1] == pytest.approx(1.0, abs=1e-9)


def test_slope_e_comparavel_entre_ativos_de_escala_absurdamente_diferente():
    # BTC a 60.000 e ITUB4 a 30, ambos subindo 0.5%/dia → MESMO slope.
    # Com preço bruto (o erro do doc original) os slopes seriam 2000x diferentes.
    a = indicators.compute(_ohlcv(60000 * 1.005 ** np.arange(300)), P)
    b = indicators.compute(_ohlcv(30 * 1.005 ** np.arange(300)), P)

    assert a["regression_slope"].iloc[-1] == pytest.approx(
        b["regression_slope"].iloc[-1], rel=1e-6
    )


def test_serie_travada_nao_divide_por_zero():
    f = indicators.compute(_ohlcv(np.full(300, 100.0)), P)

    assert f["regression_r2"].iloc[-1] == 0.0  # sem variância → sem tendência
    assert f["deviation_from_mean"].iloc[-1] == 0.0
    assert f["volume_z_score"].iloc[-1] == 0.0


def test_volume_zero_nao_vira_menos_infinito():
    # Pregão parado tem volume 0. ln(0) = -inf contaminaria a janela inteira; log1p não.
    closes = 100 + np.sin(np.arange(300) / 5)
    vols = np.full(300, 1000.0)
    vols[250] = 0.0

    f = indicators.compute(_ohlcv(closes, vols), P)

    assert np.isfinite(f["volume_z_score"].iloc[250:]).all()


def test_features_sao_nan_ate_a_janela_encher():
    # Emitir sinal com janela incompleta é calcular indicador sobre dado que não existe.
    f = indicators.compute(_ohlcv(100 + np.sin(np.arange(300) / 5)), P)

    assert f["regression_slope"].iloc[: P.regressao.janela - 1].isna().all()
    assert f.loc[P.min_velas :, indicators.FEATURES].notna().all().all()


# --------------------------------------------------------------- regime


def test_tendencia_forte_e_classificada_como_tendencia():
    f = _com_regime(_ohlcv(100 * 1.01 ** np.arange(300)))
    assert f["market_regime"].iloc[-1] == MarketRegime.TENDENCIA.value


def test_oscilacao_em_torno_da_media_e_classificada_como_lateral():
    rng = np.random.default_rng(7)
    closes = 100 + np.sin(np.arange(400) / 6) * 3 + rng.normal(0, 0.3, 400)
    f = _com_regime(_ohlcv(closes))

    # Numa lateral limpa, o regime dominante tem de ser LATERAL.
    dominante = f["market_regime"].iloc[P.min_velas :].value_counts().idxmax()
    assert dominante == MarketRegime.LATERAL.value


def test_choque_de_volatilidade_vira_nervoso():
    rng = np.random.default_rng(3)
    closes = 100 + rng.normal(0, 0.5, 400)
    df = _ohlcv(closes)
    # Vela com range 30x o normal — o ATR explode contra a própria mediana.
    df.loc[350:355, "high"] = df.loc[350:355, "close"] * 1.30
    df.loc[350:355, "low"] = df.loc[350:355, "close"] * 0.70

    f = _com_regime(df)
    assert MarketRegime.NERVOSO.value in f["market_regime"].iloc[350:365].tolist()


# --------------------------------------------------------------- regra de sinal


def test_nao_opera_reversao_em_tendencia_forte():
    """A regra que evita pegar faca caindo — o erro mais caro da reversão à média.

    Queda organizada de 1.5%/dia com um mergulho extra e volume explodindo: em −2σ, um motor
    ingênuo compraria. Aqui o regime é TENDENCIA, então NÃO existe sinal.
    """
    closes = 100 * 0.985 ** np.arange(300)
    closes[280:] *= 0.90  # capitulação: mergulha bem abaixo da banda
    vols = np.full(300, 1000.0)
    vols[280:] = 50_000.0  # z-score de volume estourando

    f = _com_regime(_ohlcv(closes, vols))
    trecho = f.iloc[280:]

    assert (trecho["market_regime"] == MarketRegime.TENDENCIA.value).all()
    assert (trecho["deviation_from_mean"] < -P.bandas.n_sigma_entrada).any()  # tocou a banda
    assert signals.generate(trecho, P, Market.CRYPTO).empty  # e ainda assim: nenhum sinal


def test_sinal_de_compra_nasce_em_lateral_com_desvio_e_volume():
    rng = np.random.default_rng(11)
    closes = 100 + rng.normal(0, 0.5, 400)
    closes[380] = 94.0  # mergulho isolado: bem abaixo de −2σ, mas sem virar tendência
    vols = np.full(400, 1000.0)
    vols[380] = 20_000.0

    f = _com_regime(_ohlcv(closes, vols))
    sinais = signals.generate(f, P, Market.CRYPTO)

    assert not sinais.empty
    s = sinais.iloc[0]
    assert s["alert_type"] == AlertType.BUY.value
    assert s["stop_loss_price"] < s["trigger_price"] < s["take_profit_price"]
    assert 0 <= s["calculated_score"] <= 100
    assert len(s["state_vector"]) == 5


def test_rr_minimo_descarta_o_toque_raso_e_aprova_o_mergulho_fundo():
    """O filtro de R:R é critério de DESCARTE — e ele MORDE.

    Tocar −2σ não basta. O alvo (μ) dista ~2σ da entrada, e o stop dista 1.5·ATR: um toque
    raso na banda dá R:R ~1 e é descartado. Só passa o mergulho fundo o bastante para o alvo
    valer o dobro do risco.

    É a contradição do documento original resolvida: ele exigia 1:2 e prescrevia níveis que
    davam 1.67:1 — as duas regras se anulavam.
    """
    rng = np.random.default_rng(5)
    closes = 100 + rng.normal(0, 0.8, 1000)
    vols = np.full(1000, 1000.0)

    # Dois mergulhos rasos (mal cruzam −2σ) e dois fundos. Volume confirma todos.
    rasos, fundos = [300, 450], [600, 750]
    for i in rasos:
        closes[i] = 98.2
    for i in fundos:
        closes[i] = 93.0
    for i in rasos + fundos:
        vols[i] = 20_000.0

    f = _com_regime(_ohlcv(closes, vols))
    sinais = signals.generate(f, P, Market.CRYPTO)

    # Todo sinal EMITIDO respeita o mínimo — essa é a invariante dura.
    assert (sinais["rr"] >= P.risco.rr_minimo).all()

    emitidos = set(sinais.index)
    assert emitidos >= set(fundos), "os mergulhos fundos deveriam passar"
    assert not (emitidos & set(rasos)), "os toques rasos deveriam ser descartados pelo R:R"


def test_sizing_mantem_a_perda_maxima_constante_entre_ativos():
    # O stop mais largo compra MENOS. A perda em reais é a mesma nos dois casos.
    qty_a = signals.size_position(banca=10_000, risco_pct=1.0, trigger=100, stop=98)
    qty_b = signals.size_position(banca=10_000, risco_pct=1.0, trigger=100, stop=90)

    assert qty_a * (100 - 98) == pytest.approx(100.0)
    assert qty_b * (100 - 90) == pytest.approx(100.0)
    assert qty_b < qty_a


# --------------------------------------------------------------- triple barrier


def _serie_barreira(highs, lows):
    n = len(highs)
    return pd.DataFrame(
        {"high": highs, "low": lows, "close": [(h + l) / 2 for h, l in zip(highs, lows)]},
        index=range(n),
    )


def test_alvo_atingido_gera_tp_liquido_de_custos():
    ohlc = _serie_barreira([100, 101, 106], [99, 100, 104])
    r = evaluate(ohlc, 0, AlertType.BUY, 100, 105, 97, horizonte=5, custo_ida_volta_pct=0.3)

    assert r.outcome is Outcome.TP
    assert r.retorno_bruto_pct == pytest.approx(5.0)
    assert r.retorno_liquido_pct == pytest.approx(4.7)  # custo saiu do resultado


def test_alvo_e_stop_na_mesma_vela_assume_o_stop():
    """O OHLC não diz qual veio primeiro. Assumir o alvo fabricaria uma borda inexistente."""
    ohlc = _serie_barreira([100, 106], [99, 96])  # a vela 1 toca 105 E 97
    r = evaluate(ohlc, 0, AlertType.BUY, 100, 105, 97, horizonte=5, custo_ida_volta_pct=0.0)

    assert r.outcome is Outcome.SL


def test_a_vela_do_proprio_sinal_nao_conta():
    """Usar o high/low da vela do gatilho é lookahead: no fechamento dela, não se sabia."""
    # A vela 0 tocaria alvo E stop (→ SL, pelo pior caso). As seguintes não tocam nada.
    ohlc = _serie_barreira([106, 101, 101, 101], [94, 100, 100, 100])
    r = evaluate(ohlc, 0, AlertType.BUY, 100, 105, 97, horizonte=3, custo_ida_volta_pct=0.0)

    assert r.outcome is Outcome.TIMEOUT  # se a vela 0 contasse, teria virado SL


def test_sem_desfecho_no_horizonte_vira_timeout_e_nao_nulo():
    ohlc = _serie_barreira([101] * 6, [99] * 6)  # nunca toca nada
    r = evaluate(ohlc, 0, AlertType.BUY, 100, 105, 97, horizonte=3, custo_ida_volta_pct=0.0)

    assert r.outcome is Outcome.TIMEOUT
    assert r.retorno_bruto_pct == pytest.approx(0.0)  # o retorno na saída É o rótulo


def test_historico_curto_demais_devolve_none_e_nao_um_rotulo_inventado():
    ohlc = _serie_barreira([101, 101], [99, 99])
    assert evaluate(ohlc, 0, AlertType.BUY, 100, 105, 97, 10, 0.0) is None


def test_venda_e_o_espelho_da_compra():
    ohlc = _serie_barreira([101, 100], [99, 94])  # cai até o alvo da venda
    r = evaluate(ohlc, 0, AlertType.SELL, 100, 95, 103, horizonte=5, custo_ida_volta_pct=0.0)

    assert r.outcome is Outcome.TP
    assert r.retorno_bruto_pct == pytest.approx(5.0)  # cair 5% numa venda é LUCRO
