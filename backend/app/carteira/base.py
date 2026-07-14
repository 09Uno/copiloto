"""De onde vem a carteira do usuário.

**Fonte plugável**, mesma lógica das classes de ativo: o resto do sistema **não sabe** de onde
a posição veio. O FinControl é UMA fonte; amanhã entra CSV, nota de corretagem, ou a API de uma
corretora — e nada mais muda.

O contrato é minúsculo de propósito. Uma fonte só precisa responder: **quais posições, com que
quantidade e a que custo médio.** Todo o resto do produto (preço teto, yield-on-cost, tese,
vigia) já funciona em cima disso.

**A venda não mexe no custo médio** — é a regra que toda fonte tem de respeitar, e o erro que
quase todo mundo comete. A venda reduz a quantidade e realiza lucro/prejuízo; o preço médio do
que sobra continua o mesmo. Recalcular na venda inflaria o yield-on-cost sem que nada tivesse
acontecido de verdade.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum


class Fonte(StrEnum):
    MANUAL = "MANUAL"
    FINCONTROL = "FINCONTROL"
    # CSV = "CSV"                 # importação de planilha
    # NOTA_CORRETAGEM = "NOTA"    # PDF da corretora
    # B3 = "B3"                   # área do investidor


@dataclass(frozen=True)
class Posicao:
    ticker: str
    quantidade: float
    custo_medio: float
    classe: str | None = None      # deduzido depois, se a fonte não souber

    @property
    def investido(self) -> float:
        return self.quantidade * self.custo_medio


@dataclass
class Carteira:
    posicoes: list[Posicao]
    fonte: Fonte

    # Opcional — nem toda fonte sabe destas coisas, e tudo bem.
    recebidos: dict[str, float] = field(default_factory=dict)
    a_receber: dict[str, float] = field(default_factory=dict)
    vendas_do_mes: float = 0.0     # base da isenção de IR (só ação)
    erros: list[str] = field(default_factory=list)

    def de(self, ticker: str) -> Posicao | None:
        alvo = ticker.strip().upper()
        return next((p for p in self.posicoes if p.ticker == alvo), None)

    @property
    def total_investido(self) -> float:
        return sum(p.investido for p in self.posicoes)


class FonteDeCarteira(ABC):
    """O plugin. Uma implementação por fonte; nada fora daqui sabe qual é."""

    fonte: Fonte

    @abstractmethod
    def puxar(self, config: dict) -> Carteira:
        """`config` vem de `carteira_fontes.config` (credenciais, URL, o que a fonte precisar)."""

    @abstractmethod
    def campos_config(self) -> dict[str, str]:
        """`nome → rótulo` do que a tela precisa pedir ao usuário para conectar esta fonte."""

    def validar(self, config: dict) -> str | None:
        """Devolve a mensagem de erro, ou None se a conexão funciona.

        Falhar **na hora de conectar** é muito melhor do que falhar silenciosamente às 20h
        do dia em que o balanço sai.
        """
        faltando = [r for c, r in self.campos_config().items() if not config.get(c)]
        return f"faltam: {', '.join(faltando)}" if faltando else None


_REGISTRO: dict[Fonte, FonteDeCarteira] = {}


def registrar(impl: FonteDeCarteira) -> None:
    _REGISTRO[impl.fonte] = impl


def para(fonte: Fonte) -> FonteDeCarteira | None:
    return _REGISTRO.get(fonte)


def disponiveis() -> dict[Fonte, dict[str, str]]:
    return {f: impl.campos_config() for f, impl in _REGISTRO.items()}


def vendas_de_acao_no_mes(
    vendas: list[tuple[date, str, float]], quando: date | None = None
) -> float:
    """Total vendido de AÇÃO no mês — a base da isenção de R$ 20 mil.

    `vendas` = (data, categoria, valor). **A isenção vale só para ação**: FII paga 20% sempre,
    sem isenção. Misturar os dois faz o usuário achar que está no limite quando não está — ou
    pior, achar que está isento quando vai pagar.
    """
    quando = quando or date.today()
    return sum(
        v
        for d, cat, v in vendas
        if d.month == quando.month
        and d.year == quando.year
        and cat.strip().lower().startswith("aç")
    )
