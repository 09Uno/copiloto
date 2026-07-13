"""Backtest — os testes que impedem o auto-engano.

Um backtest errado não avisa que está errado: ele devolve um número bonito. Estes testes
existem para que o número seja honesto, não para que seja alto.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backtest import metrics
from backtest.core import Trade, _r_multiple, to_frame


def _trade(r: float, entrada=100.0, stop=98.0, outcome="TP") -> Trade:
    return Trade(
        ticker="X", strategy="T", side="BUY",
        entrada_em=pd.Timestamp("2024-01-01", tz="UTC"),
        saida_em=pd.Timestamp("2024-01-05", tz="UTC"),
        entrada=entrada, saida=entrada, stop=stop, alvo=104.0,
        outcome=outcome, retorno_liquido_pct=r * 2.0, r_multiple=r, velas=4, score=50,
    )


# ------------------------------------------------------------- R-multiple


def test_r_multiple_normaliza_o_risco_entre_ativos():
    """O que torna comparável um trade de BTC e um de ITUB4: não é o % de ganho, é quantos
    RISCOS o trade devolveu. Ganhar 2% arriscando 1% e ganhar 20% arriscando 10% é a mesma coisa.
    """
    btc = _r_multiple(entrada=60_000, stop=59_400, retorno_liquido_pct=2.0)  # risco 1%
    itub = _r_multiple(entrada=30, stop=29.7, retorno_liquido_pct=2.0)       # risco 1%

    assert btc == pytest.approx(itub)
    assert btc == pytest.approx(2.0)


def test_perda_no_stop_e_aproximadamente_menos_1R():
    # Comprou a 100, stop em 98 (risco 2%). Bateu o stop → -2% bruto → ≈ -1R.
    assert _r_multiple(100.0, 98.0, -2.0) == pytest.approx(-1.0)


# ------------------------------------------------------------- expectância


def test_expectancia_e_o_que_decide_e_nao_a_taxa_de_acerto():
    """Dá para acertar 80% das vezes e QUEBRAR. A taxa de acerto é a métrica preferida de
    quem se engana: se os 20% de erros perdem 5× o que os 80% de acertos ganham, o resultado
    é negativo — e é a expectância que denuncia.
    """
    trades = to_frame([_trade(+0.2) for _ in range(80)] + [_trade(-1.0) for _ in range(20)])
    m = metrics.compute(trades)

    assert m.taxa_acerto == pytest.approx(80.0)   # parece ótimo…
    assert m.expectancia_r < 0                    # …e perde dinheiro
    assert not m.tem_borda


def test_estrategia_com_borda_e_reconhecida():
    # 400 trades e não 100: com 100, t = 1.36 e o próprio critério recusaria — corretamente.
    trades = to_frame([_trade(+2.0) for _ in range(160)] + [_trade(-1.0) for _ in range(240)])
    m = metrics.compute(trades)

    assert m.taxa_acerto == pytest.approx(40.0)   # erra a maioria…
    assert m.expectancia_r == pytest.approx(0.2)  # …e ganha dinheiro
    assert m.profit_factor > 1
    assert m.significante
    assert m.tem_borda


def test_profit_factor_infinito_quando_nunca_se_perde():
    m = metrics.compute(to_frame([_trade(+1.0) for _ in range(10)]))
    assert m.profit_factor == float("inf")


# ------------------------------------------------------------- equity e drawdown


def test_equity_usa_risco_fixo_por_operacao():
    """Arriscar 1% e ganhar 2R faz a banca subir 2%. Medir a estratégia por retorno cru do
    preço mediria uma estratégia que ninguém opera (SPEC §8.2).
    """
    m = metrics.compute(to_frame([_trade(+2.0)]), risco_por_trade_pct=1.0)
    assert m.retorno_total_pct == pytest.approx(2.0)


def test_drawdown_captura_a_pior_sequencia_e_nao_o_pior_trade():
    # Sobe, e depois três perdas seguidas: o drawdown é o buraco acumulado a partir do pico.
    seq = [_trade(+2.0)] + [_trade(-1.0) for _ in range(3)]
    m = metrics.compute(to_frame(seq), risco_por_trade_pct=10.0)

    # pico 1.20 → 1.20·0.9³ = 0.8748 → queda de ~27%
    assert m.max_drawdown_pct == pytest.approx(-27.1, abs=0.5)


def test_ruina_nao_vira_equity_negativa():
    """Arriscar 50% e tomar -3R levaria a equity a -50%: número sem sentido físico."""
    m = metrics.compute(to_frame([_trade(-3.0)]), risco_por_trade_pct=50.0)
    assert m.retorno_total_pct > -100.0


# ------------------------------------------------------------- buy & hold


def test_buy_and_hold_e_a_barra_a_ser_batida():
    df = pd.DataFrame({"close": [100.0, 150.0]})
    assert metrics.buy_and_hold(df) == pytest.approx(50.0)


# ------------------------------------------------------------- significância


def test_expectancia_positiva_mas_INSIGNIFICANTE_nao_e_borda():
    """O erro mais perigoso do backtest inteiro.

    Poucos trades e expectância pequena: o resultado é indistinguível de ZERO. Chamar isso de
    borda é confundir sorte com estratégia — e é assim que se acaba operando ruído com dinheiro
    de verdade. Foi o que aconteceu no EUA diário: +0,065R com erro-padrão de ±0,074R.
    """
    rng = np.random.default_rng(0)
    # Ruído puro, sem borda nenhuma, com uma média levemente positiva por acaso.
    ruido = rng.normal(0.05, 1.2, 60)
    trades = to_frame([_trade(float(x)) for x in ruido])

    m = metrics.compute(trades)

    assert m.expectancia_r > 0        # parece ter borda…
    assert not m.significante         # …mas é ruído
    assert not m.tem_borda            # e o veredito recusa


def test_expectancia_pequena_mas_com_MUITOS_trades_pode_ser_borda():
    """A mesma expectância minúscula, com amostra grande, deixa de ser sorte."""
    rng = np.random.default_rng(0)
    trades = to_frame([_trade(float(x)) for x in rng.normal(0.05, 1.2, 20_000)])

    m = metrics.compute(trades)

    assert m.significante
    assert m.tem_borda


def test_ganhar_menos_que_o_buy_and_hold_nao_e_vitoria():
    """+3% a.a. numa janela em que segurar o ativo deu +100% a.a. não é estratégia — é
    trabalho e risco em troca de menos dinheiro."""
    # Expectância de +0,16R, sólida e significante (n=300).
    trades = to_frame(
        [_trade(+0.6) for _ in range(180)] + [_trade(-0.5) for _ in range(120)]
    )
    # Mas o ativo triplicou no período: quem só comprou e esperou fez +44% a.a.
    m = metrics.compute(trades, buy_hold_pct=200.0, anos_periodo=3.0)

    assert m.tem_borda           # lucrativa E significante…
    assert not m.bate_buy_hold   # …e ainda assim, pior que não fazer nada


def test_sem_trades_nao_ha_metrica_inventada():
    assert metrics.compute(to_frame([])) is None
