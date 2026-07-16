"""Onde a avaliação vira DECISÃO.

O preço teto sozinho diz "caro ou barato". Cruzado com o **seu custo médio** e a **sua meta**,
ele responde à pergunta que você de fato faz todo mês: *"tenho R$ 1.000. Ponho aqui?"*

Dois números que quase ninguém separa, e que mudam a decisão:

  **Yield-on-cost** — o dividendo sobre o preço que VOCÊ pagou. Se você comprou TAEE3 a
  R$ 13,15 e ela paga R$ 1,08, o seu yield é **8,2% e é seu para sempre** — independente do
  que o papel faça no mercado. É por isso que vender um vencedor com tese intacta costuma ser
  o erro mais caro do investidor de dividendo: você troca um yield travado por imposto.

  **Yield atual** — o dividendo sobre o preço de HOJE. É o que um novo aporte compra. Se a ação
  subiu e o dividendo não, o novo aporte rende menos — e talvez o dinheiro sirva melhor em
  outro lugar.

Nada aqui prevê preço. Tudo vem do seu objetivo e da aritmética.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.ativos import base
from app.ativos.base import Avaliacao


class Zona(StrEnum):
    """Onde o preço de hoje cai em relação ao SEU teto e à SUA margem de segurança.

    Não é 'compre/venda'. É onde o preço está em relação ao critério que você mesmo definiu:
    a meta de yield (que gera o teto) e a margem (a folga que você exige abaixo dele).
    """

    COMPRA = "COMPRA"   # preço ≤ preço de compra: dentro da sua zona, com margem
    JUSTO = "JUSTO"     # abaixo do teto, mas sem a margem — serve, sem colchão
    CARO = "CARO"       # acima do teto: a este preço não entrega sua meta


@dataclass(frozen=True)
class ZonaCompra:
    """O preço em que vale a pena comprar, com margem — e onde o preço de hoje está frente a ele.

    `preco_compra = teto × (1 − margem)`. O teto responde "a partir de que preço deixa de servir
    à minha meta?"; a margem responde "quanta folga eu quero abaixo disso, para o caso de eu ter
    errado a conta?". Juntos viram um alvo de entrada — sem prever nada.
    """

    teto: float
    preco_compra: float
    margem_seguranca: float
    estado: Zona
    preco: float | None
    # >0: quanto o preço ainda precisa CAIR (fração) para entrar na zona. ≤0: já está nela.
    falta_cair_pct: float | None

    @property
    def na_zona(self) -> bool:
        return self.estado is Zona.COMPRA


def zona_de_compra(av: Avaliacao, margem: float) -> ZonaCompra | None:
    """A zona de compra para esta avaliação, dada a margem de segurança do usuário.

    Depende só do teto (que já vem da meta do usuário) e da margem — não toca no cache do
    avaliador, que é indexado por (ticker, meta). Composição limpa: teto puro + margem por cima.
    """
    if av.teto is None:
        return None
    margem = max(0.0, min(margem, 0.9))  # margem sã: nunca negativa, nunca zera o preço
    preco_compra = av.teto.valor * (1 - margem)

    if av.preco is None or av.preco <= 0:
        return ZonaCompra(av.teto.valor, preco_compra, margem, Zona.JUSTO, None, None)

    if av.preco > av.teto.valor:
        estado = Zona.CARO
    elif av.preco > preco_compra:
        estado = Zona.JUSTO
    else:
        estado = Zona.COMPRA

    falta = (av.preco - preco_compra) / av.preco
    return ZonaCompra(av.teto.valor, preco_compra, margem, estado, av.preco, falta)


@dataclass(frozen=True)
class Posicao:
    ticker: str
    quantidade: float
    custo_medio: float

    @property
    def investido(self) -> float:
        return self.quantidade * self.custo_medio


@dataclass(frozen=True)
class Aporte:
    """O efeito de comprar `quantidade` ao preço de hoje."""

    ticker: str
    quantidade: float
    preco: float

    custo_medio_antes: float
    custo_medio_depois: float

    yoc_antes: float | None      # yield sobre o SEU custo
    yoc_depois: float | None
    yield_atual: float | None    # yield que o mercado paga hoje

    dentro_do_teto: bool | None
    margem_teto_pct: float | None
    veredito: str
    motivos: tuple[str, ...]

    @property
    def desembolso(self) -> float:
        return self.quantidade * self.preco


def simular(
    av: Avaliacao,
    pos: Posicao | None,
    quantidade: float,
) -> Aporte | None:
    """O que acontece com a SUA posição se você comprar agora."""
    if av.preco is None or av.preco <= 0 or quantidade <= 0:
        return None

    # Nome CANÔNICO: a ação registra o dividendo por ação e o FII o rendimento por cota, ambos
    # sob `dpa`. É por isso que este módulo funciona para os dois sem saber qual é qual.
    dpa = av.metrica(base.RENDA_POR_UNIDADE)

    q0 = pos.quantidade if pos else 0.0
    cm0 = pos.custo_medio if pos else 0.0
    q1 = q0 + quantidade
    cm1 = ((q0 * cm0) + (quantidade * av.preco)) / q1 if q1 > 0 else av.preco

    yoc0 = (dpa / cm0) if (dpa and cm0 > 0) else None
    yoc1 = (dpa / cm1) if (dpa and cm1 > 0) else None
    y_hoje = (dpa / av.preco) if dpa else None

    motivos: list[str] = []

    # --- o critério, e ele vem do SEU objetivo
    if av.teto is None:
        veredito = "SEM CRITÉRIO"
        motivos.append(av.sem_criterio or "esta classe de ativo não tem preço teto")
    elif av.preco <= av.teto.valor:
        veredito = "DENTRO DO TETO"
        motivos.append(
            f"a {av.preco:.2f} o dividendo entrega {y_hoje:.1%} — sua meta é "
            f"{av.teto.meta:.0%} (teto R$ {av.teto.valor:.2f})"
            if y_hoje else f"preço abaixo do teto de R$ {av.teto.valor:.2f}"
        )
    else:
        veredito = "ACIMA DO TETO"
        excesso = (av.preco / av.teto.valor - 1) * 100
        motivos.append(
            f"você pagaria {excesso:.0f}% acima do SEU limite — a {av.preco:.2f} o "
            f"dividendo entrega só {y_hoje:.1%}, e sua meta é {av.teto.meta:.0%}"
            if y_hoje else f"preço {excesso:.0f}% acima do teto"
        )

    # --- euforia: pagar um múltiplo que você nunca pagou
    for nome, rotulo in (("pl_vs_historia", "P/L"), ("pvp_vs_historia", "P/VP")):
        r = av.metrica(nome)
        if r and r > 1.4:
            motivos.append(
                f"{rotulo} está {(r - 1) * 100:.0f}% acima da mediana histórica do próprio "
                "papel — é assim que euforia aparece em número"
            )

    # --- o aporte piora o que você já tem?
    if yoc0 and yoc1 and yoc1 < yoc0 * 0.97:
        motivos.append(
            f"o aporte derruba seu yield-on-cost de {yoc0:.2%} para {yoc1:.2%} — "
            "você está comprando mais caro do que já tem"
        )

    motivos.extend(av.alertas)

    return Aporte(
        ticker=av.ticker, quantidade=quantidade, preco=av.preco,
        custo_medio_antes=cm0, custo_medio_depois=cm1,
        yoc_antes=yoc0, yoc_depois=yoc1, yield_atual=y_hoje,
        dentro_do_teto=av.abaixo_do_teto, margem_teto_pct=av.margem_pct,
        veredito=veredito, motivos=tuple(motivos),
    )
