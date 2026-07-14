"""O laço de vigilância.

O teste central é `test_o_silencio_e_o_produto`. Se o vigia avisar toda semana que "a Klabin
continua endividada", você aprende a ignorá-lo — e no dia em que algo importante quebrar, vai
ignorar também. **Alerta repetido é alerta morto.**
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.ativos.base import Avaliacao, Classe, Metrica
from app.tese import motor as tm
from app.tese.motor import Pilar
from app.vigia import motor as vm


def _av(**metricas) -> Avaliacao:
    return Avaliacao(
        ticker="KLBN4", classe=Classe.ACAO, preco=3.49,
        metricas={k: Metrica(k, k, v) for k, v in metricas.items()},
        teto=None,
    )


def _p(pid: int, metrica: str, op: str, limite: float, prazo: date | None = None) -> Pilar:
    return Pilar(id=pid, metrica=metrica, operador=op, limite=limite, prazo=prazo)


def _ver(av, pilares, hoje=None):
    return tm.verificar(av, "tese", pilares, hoje=hoje)


# --------------------------------------------------------------- o silêncio


def test_o_silencio_e_o_produto():
    """Nada mudou desde a última checagem → NENHUM evento. Não é falha: é a funcionalidade."""
    av = _av(payout=0.71, roe=0.20)
    pilares = [_p(1, "payout", "<", 0.90), _p(2, "roe", ">", 0.15)]
    anterior = {1: True, 2: True}  # já estavam de pé

    assert vm.diff(_ver(av, pilares), anterior) == []


def test_pilar_que_continua_caido_NAO_avisa_de_novo():
    """Ele já caiu e você já foi avisado. Repetir todo mês faria você parar de ler."""
    av = _av(divida_ebit=7.6)
    pilares = [_p(1, "divida_ebit", "<", 3.0)]

    assert vm.diff(_ver(av, pilares), {1: False}) == []


# --------------------------------------------------------------- o que É notícia


def test_pilar_que_CAI_e_noticia():
    av = _av(payout=1.05)
    ev = vm.diff(_ver(av, [_p(1, "payout", "<", 0.90)]), {1: True})

    assert len(ev) == 1
    assert ev[0].tipo is vm.Tipo.PILAR_CAIU
    assert "Você compraria hoje" in ev[0].pergunta  # nunca diz "venda"


def test_pilar_que_VOLTA_tambem_e_noticia():
    av = _av(payout=0.60)
    ev = vm.diff(_ver(av, [_p(1, "payout", "<", 0.90)]), {1: False})

    assert ev[0].tipo is vm.Tipo.PILAR_VOLTOU


def test_pilar_que_ja_NASCE_caido_e_noticia():
    """Nunca checado (`None`) e já caído: você precisa saber."""
    av = _av(payout=1.05)
    ev = vm.diff(_ver(av, [_p(1, "payout", "<", 0.90)]), {})

    assert ev[0].tipo is vm.Tipo.PILAR_CAIU


# --------------------------------------------------------------- as apostas


def test_aposta_em_curso_NAO_e_alarme():
    """Ela nasce falsa DE PROPÓSITO. Alarmar seria ruído — e o prazo ainda não venceu."""
    futuro = date.today() + timedelta(days=365)
    av = _av(cresc_lucro=-0.64)
    ev = vm.diff(_ver(av, [_p(1, "cresc_lucro", ">", 0, prazo=futuro)]), {})

    assert ev == []


def test_aposta_que_VENCE_o_prazo_e_a_noticia_mais_importante():
    """E ela avisa TODO MÊS, de propósito: uma aposta perdida não some sozinha — fica cobrando
    uma decisão até você tomar uma."""
    venceu = date.today() - timedelta(days=1)
    av = _av(cresc_lucro=-0.64)
    p = [_p(1, "cresc_lucro", ">", 0, prazo=venceu)]

    ev = vm.diff(_ver(av, p), {1: False})   # mesmo já sabendo que estava falso
    assert len(ev) == 1
    assert ev[0].tipo is vm.Tipo.APOSTA_PERDIDA
    assert "ainda vai virar" in ev[0].pergunta

    # E é o evento de MAIOR prioridade — vem antes de tudo.
    assert vm.PRIORIDADE[vm.Tipo.APOSTA_PERDIDA] == 0


def test_aposta_que_VIRA_e_comemorada():
    futuro = date.today() + timedelta(days=365)
    av = _av(cresc_lucro=0.12)
    ev = vm.diff(_ver(av, [_p(1, "cresc_lucro", ">", 0, prazo=futuro)]), {1: False})

    assert ev[0].tipo is vm.Tipo.APOSTA_VENCEU


# --------------------------------------------------------------- a porta de entrada


def test_comprar_sem_escrever_o_porque_e_cobrado():
    """É assim que o autoengano começa: sem o motivo escrito, não há como saber quando ele
    deixou de valer — e aí se faz preço médio numa tese morta."""
    e = vm.posicao_sem_tese("VALE3", 5000.0)

    assert e.tipo is vm.Tipo.POSICAO_SEM_TESE
    assert e.pergunta == "Por que você comprou?"


def test_a_isencao_de_IR_avisa_ANTES_de_estourar():
    e = vm.isencao_ir(18_500.0)

    assert "faltam R$ 1,500.00" in e.corpo
    assert "TODO o ganho do mês" in e.corpo  # não só o excedente — é o que quase todos erram


def test_a_ordem_poe_o_mais_grave_primeiro():
    ev = vm.ordenar([
        vm.posicao_sem_tese("X", 100),
        vm.isencao_ir(19_000),
        vm.Evento(vm.Tipo.APOSTA_PERDIDA, "KLBN4", "t", "c"),
    ])

    assert ev[0].tipo is vm.Tipo.APOSTA_PERDIDA
