"""Motor da tese. Módulo puro.

**O motor não sabe o que é "payout".** Ele recebe um pilar — `(métrica, operador, limite)` —,
pergunta à classe do ativo *"você sabe calcular `payout`?"*, recebe o número e compara. Só isso.

É essa ignorância deliberada que torna o sistema extensível: quando entrar a classe FII, ela
traz `p_vp` e `alavancagem`; quando entrar renda fixa, traz `taxa_real` e `duration`. **Você
escreve pilares com as métricas novas e ninguém toca aqui.**

E ele **nunca diz "venda"**. Ele devolve a SUA decisão com os fatos atualizados:

    "Você comprou por 5 motivos. Sobraram 3. Você compraria hoje, sabendo disso?"

É isso que impede as duas coisas mais caras da bolsa: fazer preço médio numa tese **morta** (a
ação não está "mais barata" — está **pior**) e vender um vencedor cuja tese está **intacta** (o
mercado só ficou mal-humorado).
"""

from __future__ import annotations

import operator
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from app.ativos.base import Avaliacao

OPERADORES = {
    "<": operator.lt,
    "<=": operator.le,
    ">": operator.gt,
    ">=": operator.ge,
}


class Estado(StrEnum):
    OK = "OK"                        # o pilar continua de pé
    CAIU = "CAIU"                    # o pilar não vale mais
    APOSTA_EM_CURSO = "APOSTANDO"    # ainda falso, mas o prazo não venceu
    APOSTA_PERDIDA = "PERDEU"        # o prazo venceu e não virou — você estava errado
    NAO_VERIFICAVEL = "?"            # a métrica não está disponível hoje
    PERGUNTAR = "PERGUNTAR"          # qualitativo: só você pode julgar


@dataclass(frozen=True)
class Pilar:
    id: int | None
    metrica: str | None
    operador: str | None
    limite: float | None
    valor_na_criacao: float | None = None
    qualitativo: bool = False
    descricao: str | None = None

    # Aposta em recuperação: hoje é falso, e tudo bem — mas tem prazo.
    # Sem prazo, "ainda não virou, mas vai virar" vira desculpa eterna.
    prazo: date | None = None

    @property
    def e_aposta(self) -> bool:
        return self.prazo is not None

    def __str__(self) -> str:
        if self.qualitativo:
            return self.descricao or "(qualitativo)"
        base = f"{self.metrica} {self.operador} {self.limite:g}"
        # Sem colchetes: o `rich` os interpreta como marcação de estilo e ENGOLE o texto —
        # o prazo da aposta sumia da tela, que é justamente o que não pode sumir.
        return f"{base}  ⏳ aposta até {self.prazo:%m/%Y}" if self.prazo else base


@dataclass(frozen=True)
class Resultado:
    pilar: Pilar
    estado: Estado
    valor: float | None
    motivo: str | None = None


@dataclass(frozen=True)
class Veredito:
    ticker: str
    resumo: str
    resultados: list[Resultado]

    @property
    def de_pe(self) -> int:
        return sum(1 for r in self.resultados if r.estado is Estado.OK)

    @property
    def cairam(self) -> list[Resultado]:
        return [r for r in self.resultados if r.estado is Estado.CAIU]

    @property
    def apostas_perdidas(self) -> list[Resultado]:
        return [r for r in self.resultados if r.estado is Estado.APOSTA_PERDIDA]

    @property
    def apostas_em_curso(self) -> list[Resultado]:
        return [r for r in self.resultados if r.estado is Estado.APOSTA_EM_CURSO]

    @property
    def total_verificaveis(self) -> int:
        return sum(1 for r in self.resultados if not r.pilar.qualitativo)

    @property
    def intacta(self) -> bool:
        """Aposta EM CURSO não quebra a tese — ela ainda tem prazo. Aposta PERDIDA, sim."""
        return not self.cairam and not self.apostas_perdidas

    @property
    def pergunta(self) -> str:
        """O sistema NÃO decide. Ele devolve a decisão, com os fatos atualizados."""
        if self.apostas_perdidas:
            quais = ", ".join(str(r.pilar) for r in self.apostas_perdidas)
            return (
                f"**O prazo da sua aposta venceu e ela não virou** ({quais}).\n"
                "  Isto não é 'ainda vai virar' — é uma aposta perdida. Você estava errado, "
                "e reconhecer isso agora é a decisão.\n"
                "  Se quiser dar mais tempo, tudo bem — mas então escreva o NOVO prazo, e "
                "assuma que já errou uma vez."
            )
        if self.cairam:
            return (
                f"Você comprou por {self.total_verificaveis} motivos verificáveis. "
                f"Caíram {len(self.cairam)}. **Você compraria hoje, sabendo disso?**"
            )
        if self.apostas_em_curso:
            return (
                "Nenhum pilar caiu, e a aposta ainda tem prazo. Nada mudou para pior — "
                "mas o relógio está correndo."
            )
        return (
            "Nenhum pilar caiu. Se a ação caiu, foi o mercado que mudou de humor — "
            "não a empresa. Você venderia por quê?"
        )


def verificar(
    av: Avaliacao, resumo: str, pilares: list[Pilar], hoje: date | None = None
) -> Veredito:
    """Checa cada pilar contra as métricas que a CLASSE DO ATIVO calcula."""
    hoje = hoje or date.today()
    out: list[Resultado] = []

    for p in pilares:
        if p.qualitativo:
            # O sistema não finge que sabe julgar "monopólio regulado". Ele te pergunta.
            out.append(Resultado(p, Estado.PERGUNTAR, None,
                                 "só você pode julgar — continua valendo?"))
            continue

        valor = av.metrica(p.metrica)
        if valor is None:
            out.append(Resultado(
                p, Estado.NAO_VERIFICAVEL, None,
                f"a classe {av.classe.value} não tem `{p.metrica}` disponível hoje",
            ))
            continue

        cmp = OPERADORES.get(p.operador)
        if cmp is None:
            out.append(Resultado(p, Estado.NAO_VERIFICAVEL, valor,
                                 f"operador inválido: {p.operador}"))
            continue

        passou = bool(cmp(valor, p.limite))

        if passou:
            estado, motivo = Estado.OK, None
            if p.e_aposta:
                estado = Estado.OK
                motivo = "a aposta VIROU — virou pilar de verdade"
        elif p.e_aposta:
            # Aposta ainda falsa: só é derrota quando o PRAZO vence.
            if hoje > p.prazo:
                estado = Estado.APOSTA_PERDIDA
                motivo = (
                    f"o prazo venceu em {p.prazo:%m/%Y} e não virou "
                    f"(hoje {valor:g}, você esperava {p.operador} {p.limite:g}). "
                    "Você estava errado — e admitir isso é a decisão."
                )
            else:
                falta = (p.prazo - hoje).days
                estado = Estado.APOSTA_EM_CURSO
                motivo = (
                    f"ainda falso ({valor:g}), mas era esperado — faltam "
                    f"{falta // 30} meses para o prazo de {p.prazo:%m/%Y}"
                )
        else:
            estado, motivo = Estado.CAIU, _porque_caiu(p, valor)

        out.append(Resultado(p, estado, valor, motivo))

    return Veredito(ticker=av.ticker, resumo=resumo, resultados=out)


def _porque_caiu(p: Pilar, valor: float) -> str:
    antes = (
        f" (era {p.valor_na_criacao:g} quando você comprou)"
        if p.valor_na_criacao is not None
        else ""
    )
    return f"hoje {valor:g} — você exigia {p.operador} {p.limite:g}{antes}"


def parse_pilar(texto: str, metricas_validas: dict[str, str]) -> Pilar:
    """Lê 'payout<0.80' e valida contra as métricas que a CLASSE de fato calcula.

    **Rejeitar aqui é o ponto.** Um pilar com uma métrica que não existe passaria a vida
    marcado como "não verificável" — silenciosamente inútil. Melhor recusar na hora, dizendo
    o que existe.

    Aposta em recuperação leva prazo: `divida_ebit<5.0@2028-06`.
    """
    prazo: date | None = None
    if "@" in texto:
        texto, _, quando = texto.partition("@")
        try:
            prazo = date.fromisoformat(quando.strip() + ("-01" if len(quando.strip()) == 7
                                                         else ""))
        except ValueError:
            raise ValueError(
                f"prazo inválido: `{quando}`. Use AAAA-MM (ex.: `divida_ebit<5.0@2028-06`)."
            ) from None

    for op in ("<=", ">=", "<", ">"):
        if op in texto:
            nome, _, limite = texto.partition(op)
            nome = nome.strip()
            if nome not in metricas_validas:
                disponiveis = ", ".join(sorted(metricas_validas))
                raise ValueError(
                    f"`{nome}` não é uma métrica desta classe de ativo.\n"
                    f"Disponíveis: {disponiveis}"
                )
            try:
                v = float(limite.strip().rstrip("%")) / (
                    100.0 if limite.strip().endswith("%") else 1.0
                )
            except ValueError:
                raise ValueError(f"limite inválido em `{texto}`") from None

            return Pilar(id=None, metrica=nome, operador=op, limite=v, prazo=prazo)

    raise ValueError(
        f"`{texto}` não é um pilar verificável. Use `metrica<valor` — por exemplo "
        "`payout<80%` ou `p_vp<1.0`.\n"
        '"vai subir" e "empresa boa" não são teses: são torcida. Não dá para checar.\n'
        "Para um pilar que só você julga, use --pilar-q \"monopólio regulado\"."
    )
