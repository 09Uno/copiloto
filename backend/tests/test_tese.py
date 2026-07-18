"""O motor da tese.

O ponto central, e o que o torna extensível: **ele não sabe o que é "payout"**. Recebe um pilar
`(métrica, operador, limite)`, pergunta à classe do ativo se ela sabe calcular aquela métrica,
recebe o número e compara. Só isso.

E ele **nunca diz "venda"**. Devolve a decisão ao dono do dinheiro, com os fatos atualizados.
"""

from __future__ import annotations

import pytest

from app.ativos.base import Avaliacao, Classe, Metrica
from app.tese import motor
from app.tese.motor import Estado, Pilar


def _av(**metricas) -> Avaliacao:
    return Avaliacao(
        ticker="TAEE3", classe=Classe.ACAO, preco=13.67,
        metricas={k: Metrica(k, k, v) for k, v in metricas.items()},
        teto=None,
    )


def _p(metrica: str, op: str, limite: float, na_criacao: float | None = None) -> Pilar:
    return Pilar(id=1, metrica=metrica, operador=op, limite=limite,
                 valor_na_criacao=na_criacao)


# --------------------------------------------------------------- o pilar precisa ser checável


def test_torcida_nao_e_tese():
    """"vai subir" e "empresa boa" não dão para verificar. Recusar na hora é o ponto: um pilar
    com métrica inexistente passaria a vida marcado como "não verificável" — inútil em silêncio.
    """
    validas = {"payout": "…", "roe": "…"}

    with pytest.raises(ValueError, match="não é um pilar verificável"):
        motor.parse_pilar("vai subir", validas)

    with pytest.raises(ValueError, match="não é uma métrica desta classe"):
        motor.parse_pilar("empresa_boa<1", validas)


def test_o_erro_ENSINA_o_que_existe():
    with pytest.raises(ValueError, match="payout, roe"):
        motor.parse_pilar("vacancia<0.1", {"payout": "…", "roe": "…"})


def test_percentual_e_fracao_significam_a_mesma_coisa():
    validas = {"payout": "…"}
    assert motor.parse_pilar("payout<80%", validas).limite == pytest.approx(0.80)
    assert motor.parse_pilar("payout<0.80", validas).limite == pytest.approx(0.80)


def test_numero_pelado_em_metrica_de_pct_e_lido_como_porcentagem():
    """No texto cru, 'dy>6' quer dizer 6%, não 600% — que é o que a pessoa quase sempre quis.
    A CLASSE informa quais métricas são de %; o motor não decide isso sozinho."""
    validas = {"dy": "…", "pl": "…"}
    pct = {"dy"}  # dy é %, pl é múltiplo

    # número pelado numa métrica de %: vira porcentagem
    assert motor.parse_pilar("dy>6", validas, pct).limite == pytest.approx(0.06)
    # fração e explícito continuam iguais — nada quebra
    assert motor.parse_pilar("dy>0.06", validas, pct).limite == pytest.approx(0.06)
    assert motor.parse_pilar("dy>6%", validas, pct).limite == pytest.approx(0.06)
    # múltiplo (não é %) fica LITERAL: pl<12 é 12, não 0,12
    assert motor.parse_pilar("pl<12", validas, pct).limite == pytest.approx(12)
    # sem informar 'percentuais', o comportamento antigo é preservado (pelado = literal)
    assert motor.parse_pilar("dy>6", validas).limite == pytest.approx(6)


# --------------------------------------------------------------- a verificação


def test_o_motor_NAO_sabe_o_que_e_payout():
    """Ele pergunta à classe do ativo. Por isso o FII traz `p_vp` e `alavancagem`, a renda fixa
    trará `taxa_real` — e você escreve pilares com elas sem ninguém tocar aqui."""
    av = _av(payout=0.71, roe=0.197)
    v = motor.verificar(av, "…", [_p("payout", "<", 0.90), _p("roe", ">", 0.15)])

    assert v.intacta
    assert v.de_pe == 2


def test_pilar_que_cai_diz_o_que_MUDOU():
    av = _av(divida_ebit=3.94)
    v = motor.verificar(av, "…", [_p("divida_ebit", "<", 3.0, na_criacao=2.1)])

    r = v.resultados[0]
    assert r.estado is Estado.CAIU
    assert "3.94" in r.motivo
    assert "era 2.1 quando você comprou" in r.motivo


def test_metrica_indisponivel_nao_vira_falso_ok_nem_falso_alarme():
    """Não saber é diferente de estar quebrado. Tratar ausência como falha geraria alarme
    falso; tratar como sucesso esconderia o problema."""
    v = motor.verificar(_av(payout=0.5), "…", [_p("vacancia", "<", 0.10)])

    assert v.resultados[0].estado is Estado.NAO_VERIFICAVEL
    assert v.intacta, "métrica ausente NÃO é pilar caído"
    assert "não tem `vacancia`" in v.resultados[0].motivo


def test_pilar_qualitativo_e_devolvido_a_voce():
    """"Monopólio regulado" o sistema não sabe julgar — e não finge que sabe. Ele PERGUNTA."""
    q = Pilar(id=1, metrica=None, operador=None, limite=None,
              qualitativo=True, descricao="monopólio regulado")
    v = motor.verificar(_av(payout=0.5), "…", [q])

    assert v.resultados[0].estado is Estado.PERGUNTAR
    assert v.total_verificaveis == 0, "qualitativo não entra na contagem de verificáveis"


# --------------------------------------------------------------- o veredito


def test_o_sistema_NUNCA_diz_venda():
    """Ele devolve a SUA decisão com os fatos atualizados. Quem decide é o dono do dinheiro."""
    v = motor.verificar(
        _av(payout=0.71, divida_ebit=3.94),
        "…",
        [_p("payout", "<", 0.90), _p("divida_ebit", "<", 3.0)],
    )

    assert not v.intacta
    assert len(v.cairam) == 1
    assert "Você compraria hoje" in v.pergunta
    assert "venda" not in v.pergunta.lower()


def test_tese_intacta_defende_o_vencedor_da_venda_nervosa():
    """A ação caiu 20% e os pilares seguem de pé? Então NÃO ACONTECEU NADA — o mercado só ficou
    mal-humorado. É aí que se compra mais, não que se vende."""
    v = motor.verificar(_av(payout=0.71, roe=0.20), "…",
                        [_p("payout", "<", 0.90), _p("roe", ">", 0.15)])

    assert v.intacta
    assert "Você venderia por quê?" in v.pergunta
