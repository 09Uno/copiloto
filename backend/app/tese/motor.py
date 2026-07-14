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
from enum import StrEnum

from app.ativos.base import Avaliacao

OPERADORES = {
    "<": operator.lt,
    "<=": operator.le,
    ">": operator.gt,
    ">=": operator.ge,
}


class Estado(StrEnum):
    OK = "OK"                    # o pilar continua de pé
    CAIU = "CAIU"                # o pilar não vale mais
    NAO_VERIFICAVEL = "?"        # a métrica não está disponível hoje
    PERGUNTAR = "PERGUNTAR"      # qualitativo: só você pode julgar


@dataclass(frozen=True)
class Pilar:
    id: int | None
    metrica: str | None
    operador: str | None
    limite: float | None
    valor_na_criacao: float | None = None
    qualitativo: bool = False
    descricao: str | None = None

    def __str__(self) -> str:
        if self.qualitativo:
            return self.descricao or "(qualitativo)"
        return f"{self.metrica} {self.operador} {self.limite:g}"


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
    def total_verificaveis(self) -> int:
        return sum(1 for r in self.resultados if not r.pilar.qualitativo)

    @property
    def intacta(self) -> bool:
        return not self.cairam

    @property
    def pergunta(self) -> str:
        """O sistema NÃO decide. Ele devolve a decisão, com os fatos atualizados."""
        if self.intacta:
            return (
                "Nenhum pilar caiu. Se a ação caiu, foi o mercado que mudou de humor — "
                "não a empresa. Você venderia por quê?"
            )
        return (
            f"Você comprou por {self.total_verificaveis} motivos verificáveis. "
            f"Caíram {len(self.cairam)}. **Você compraria hoje, sabendo disso?**"
        )


def verificar(av: Avaliacao, resumo: str, pilares: list[Pilar]) -> Veredito:
    """Checa cada pilar contra as métricas que a CLASSE DO ATIVO calcula."""
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
        out.append(Resultado(
            p,
            Estado.OK if passou else Estado.CAIU,
            valor,
            None if passou else _porque_caiu(p, valor),
        ))

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
    """
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

            return Pilar(id=None, metrica=nome, operador=op, limite=v)

    raise ValueError(
        f"`{texto}` não é um pilar verificável. Use `metrica<valor` — por exemplo "
        "`payout<80%` ou `p_vp<1.0`.\n"
        '"vai subir" e "empresa boa" não são teses: são torcida. Não dá para checar.\n'
        "Para um pilar que só você julga, use --pilar-q \"monopólio regulado\"."
    )
