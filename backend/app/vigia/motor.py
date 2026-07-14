"""O laço de vigilância.

Sem ele, as teses são um museu: só são checadas se você **lembrar de rodar um comando**. Você
não vai lembrar. Ninguém lembra. Daqui a três meses sai o balanço, um pilar cai, e você não fica
sabendo.

**O princípio que decide se isto serve ou vira spam: só avisa quando algo MUDA.**

Se ele mandar toda semana "a Klabin continua com dívida alta", você aprende a ignorar — e no dia
em que algo importante quebrar, vai ignorar também. Alerta repetido é alerta morto.
**Silêncio quando nada aconteceu é uma funcionalidade**, não uma falha.

O que É notícia:
  · um pilar CAIU (estava de pé)
  · um pilar VOLTOU (estava caído)
  · uma APOSTA VENCEU (virou pilar de verdade)
  · uma APOSTA foi PERDIDA (o prazo venceu)
  · você comprou algo e não escreveu POR QUÊ
  · você vendeu tudo de um papel que ainda tem tese
  · a isenção de IR do mês está perto do limite

O que NÃO é notícia: tudo continuar como estava.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.tese.motor import Estado, Resultado, Veredito


class Tipo(StrEnum):
    PILAR_CAIU = "PILAR_CAIU"
    PILAR_VOLTOU = "PILAR_VOLTOU"
    APOSTA_VENCEU = "APOSTA_VENCEU"
    APOSTA_PERDIDA = "APOSTA_PERDIDA"
    POSICAO_SEM_TESE = "POSICAO_SEM_TESE"
    TESE_ORFA = "TESE_ORFA"
    ISENCAO_IR = "ISENCAO_IR"


PRIORIDADE = {
    Tipo.APOSTA_PERDIDA: 0,
    Tipo.PILAR_CAIU: 1,
    Tipo.POSICAO_SEM_TESE: 2,
    Tipo.ISENCAO_IR: 3,
    Tipo.TESE_ORFA: 4,
    Tipo.APOSTA_VENCEU: 5,
    Tipo.PILAR_VOLTOU: 6,
}


@dataclass(frozen=True)
class Evento:
    tipo: Tipo
    ticker: str
    titulo: str
    corpo: str
    pergunta: str | None = None

    @property
    def icone(self) -> str:
        return {
            Tipo.APOSTA_PERDIDA: "💀",
            Tipo.PILAR_CAIU: "⚠️",
            Tipo.POSICAO_SEM_TESE: "❓",
            Tipo.ISENCAO_IR: "💰",
            Tipo.TESE_ORFA: "🗑️",
            Tipo.APOSTA_VENCEU: "🎯",
            Tipo.PILAR_VOLTOU: "✅",
        }[self.tipo]


def diff(
    v: Veredito,
    anterior: dict[int, bool | None],
    preco: float | None = None,
    preco_na_criacao: float | None = None,
) -> list[Evento]:
    """Compara o estado de AGORA com o da última checagem. Só o que mudou vira evento.

    `anterior` = pilar_id → passou (da última vez). `None` = nunca foi checado.
    """
    eventos: list[Evento] = []

    for r in v.resultados:
        pid = r.pilar.id
        antes = anterior.get(pid) if pid is not None else None

        if r.estado is Estado.APOSTA_PERDIDA:
            # Notícia todo mês, e de propósito: uma aposta perdida NÃO some sozinha. Ela fica
            # ali cobrando uma decisão até você tomar uma.
            eventos.append(_aposta_perdida(v, r, preco, preco_na_criacao))
            continue

        if r.estado is Estado.OK and antes is False:
            eventos.append(
                Evento(
                    Tipo.APOSTA_VENCEU if r.pilar.e_aposta else Tipo.PILAR_VOLTOU,
                    v.ticker,
                    (
                        f"{v.ticker}: a APOSTA virou"
                        if r.pilar.e_aposta
                        else f"{v.ticker}: um pilar voltou"
                    ),
                    f"{r.pilar}  →  hoje {r.valor:g}",
                    None,
                )
            )

        elif r.estado is Estado.CAIU and antes is not False:
            # `antes is not False` cobre True (estava de pé) e None (nunca checado, e já
            # nasceu caído — o que também é notícia).
            eventos.append(_pilar_caiu(v, r, preco, preco_na_criacao))

    return eventos


def _mov(preco: float | None, na_criacao: float | None) -> str:
    if not preco or not na_criacao:
        return ""
    var = (preco / na_criacao - 1) * 100
    return f"\nO papel está {var:+.1f}% desde a sua compra (R$ {na_criacao:.2f} → R$ {preco:.2f})."


def _pilar_caiu(v, r: Resultado, preco, na_criacao) -> Evento:
    return Evento(
        Tipo.PILAR_CAIU,
        v.ticker,
        f"{v.ticker}: um pilar da sua tese CAIU",
        f"{v.resumo}\n\n✗ {r.pilar}\n   {r.motivo}{_mov(preco, na_criacao)}",
        # O sistema NUNCA diz "venda". Devolve a decisão, com os fatos atualizados.
        "Você compraria hoje, sabendo disso?",
    )


def _aposta_perdida(v, r: Resultado, preco, na_criacao) -> Evento:
    return Evento(
        Tipo.APOSTA_PERDIDA,
        v.ticker,
        f"{v.ticker}: sua APOSTA venceu o prazo e não virou",
        f"{v.resumo}\n\n💀 {r.pilar}\n   {r.motivo}{_mov(preco, na_criacao)}",
        "Isto não é 'ainda vai virar'. Você estava errado — e reconhecer agora é a decisão.",
    )


def posicao_sem_tese(ticker: str, investido: float) -> Evento:
    """A porta de entrada. Comprar sem escrever o porquê é como o autoengano começa."""
    return Evento(
        Tipo.POSICAO_SEM_TESE,
        ticker,
        f"{ticker}: você comprou e não escreveu POR QUÊ",
        f"R$ {investido:,.2f} na carteira, sem tese registrada.\n"
        "Sem o motivo escrito, não há como saber quando ele deixou de valer — e é assim que "
        "se acaba fazendo preço médio numa tese morta.",
        "Por que você comprou?",
    )


def tese_orfa(ticker: str) -> Evento:
    return Evento(
        Tipo.TESE_ORFA,
        ticker,
        f"{ticker}: você vendeu tudo, mas a tese continua ativa",
        "A posição zerou. Encerre a tese com o motivo — é assim que se constrói o histórico "
        "do próprio julgamento.",
        "Por que você vendeu?",
    )


def isencao_ir(vendido: float, limite: float = 20_000.0) -> Evento:
    falta = limite - vendido
    return Evento(
        Tipo.ISENCAO_IR,
        "—",
        "Atenção à isenção de IR deste mês",
        f"Você já vendeu R$ {vendido:,.2f} em AÇÕES este mês. O limite da isenção é "
        f"R$ {limite:,.2f} — faltam R$ {falta:,.2f}.\n"
        "Passando disso, você paga 15% sobre TODO o ganho do mês, não só sobre o excedente.\n"
        "(FII não tem isenção: paga 20% sempre.)",
        "Dá para esperar o mês virar?",
    )


def ordenar(eventos: list[Evento]) -> list[Evento]:
    return sorted(eventos, key=lambda e: PRIORIDADE[e.tipo])
