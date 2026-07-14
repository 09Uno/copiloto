"""O contrato que toda classe de ativo cumpre.

**O sistema não pode ser quadrado.** A carteira já tem seis classes (ação, FII, ETF, BDR,
cripto, renda fixa) e vai ter mais. Cravar "preço teto = dividendo ÷ meta de yield" no coração
do sistema seria assumir que tudo é ação — e aí FII, ETF e Bitcoin entram na marra, com números
que não significam nada.

Cada classe é um **plugin** que responde às mesmas três perguntas, do jeito dela:

  1. `metricas()`   — que números eu sei calcular? (ação: LPA, DPA, ROE… / cripto: NENHUM)
  2. `teto()`       — o que define "caro" aqui? (ação: teto de yield / cripto: NÃO EXISTE)
  3. `pilares()`    — que condições a tese pode verificar?

E o motor da tese **não conhece "payout"**. Ele pergunta à classe *"você sabe calcular
`payout`?"*, recebe o número, e compara com o limite que você escreveu. Por isso uma classe
nova traz métricas novas — e você pode escrever pilares com elas **sem tocar no motor**.

**A honestidade fica embutida.** Para o Bitcoin, a classe responde: *"não tenho métrica, não
tenho teto, não sei dizer se está caro"* — e o sistema **diz isso na tela**, em vez de fabricar
um score. É a mesma disciplina que matou o robô de sinais: melhor admitir que não sei do que
inventar convicção.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum


class Classe(StrEnum):
    ACAO = "ACAO"
    FII = "FII"
    ETF = "ETF"
    BDR = "BDR"
    CRIPTO = "CRIPTO"
    RENDA_FIXA = "RENDA_FIXA"


@dataclass(frozen=True)
class Metrica:
    """Um número que a classe sabe calcular, e o que ele significa."""

    nome: str            # 'payout', 'roe', 'vacancia' — é isto que a tese referencia
    rotulo: str
    valor: float | None
    formato: str = "{:.2f}"
    melhor_alto: bool = True   # ROE alto é bom; dívida alta, não

    def __str__(self) -> str:
        return self.formato.format(self.valor) if self.valor is not None else "—"


@dataclass(frozen=True)
class Teto:
    """O preço acima do qual o ativo **deixa de servir ao seu objetivo**.

    Não é previsão. Não diz que o ativo vai cair. Diz que, acima daqui, ele não entrega
    o que VOCÊ decidiu que quer — e o critério é seu, não do mercado.
    """

    valor: float
    criterio: str        # "dividendo R$ 1,28 ÷ meta 8%"
    meta: float


@dataclass(frozen=True)
class Avaliacao:
    ticker: str
    classe: Classe
    preco: float | None
    metricas: dict[str, Metrica]
    teto: Teto | None
    alertas: tuple[str, ...] = ()

    # Quando a classe não sabe avaliar, ela DIZ — e o sistema mostra isto, não um score.
    sem_criterio: str | None = None

    @property
    def abaixo_do_teto(self) -> bool | None:
        if self.teto is None or self.preco is None:
            return None
        return self.preco <= self.teto.valor

    @property
    def margem_pct(self) -> float | None:
        """Quanto o preço está abaixo (+) ou acima (−) do teto."""
        if self.teto is None or self.preco is None or self.preco <= 0:
            return None
        return (self.teto.valor - self.preco) / self.preco * 100

    def metrica(self, nome: str) -> float | None:
        m = self.metricas.get(nome)
        return m.valor if m else None


class ClasseDeAtivo(ABC):
    """O plugin. Uma implementação por classe; nada fora daqui precisa saber qual é."""

    classe: Classe

    @abstractmethod
    def avaliar(self, ticker: str, preco: float | None, meta_yield: float) -> Avaliacao:
        """Métricas + teto para este ativo, hoje."""

    @abstractmethod
    def metricas_disponiveis(self) -> dict[str, str]:
        """`nome → rótulo` das métricas que a tese pode usar como pilar.

        **Vazio é uma resposta legítima** — e é a do Bitcoin.
        """


_REGISTRO: dict[Classe, ClasseDeAtivo] = {}


def registrar(impl: ClasseDeAtivo) -> None:
    _REGISTRO[impl.classe] = impl


def para(classe: Classe) -> ClasseDeAtivo | None:
    return _REGISTRO.get(classe)


def classificar(ticker: str) -> Classe:
    """Deduz a classe pelo ticker (convenção da B3).

    Não é infalível (GOLD11 é ETF e GARE11 é FII — ambos terminam em 11), por isso o
    cadastro do ativo pode sobrescrever. Isto é só o palpite inicial.
    """
    t = ticker.strip().upper()

    if t.endswith(("USDT", "USDC")) or t in {"BTC", "ETH", "XRP", "SOL", "ADA", "DOT"}:
        return Classe.CRIPTO
    if len(t) == 6 and t[4:] in {"34", "35", "39"}:  # BDR: 4 letras + 34/35/39
        return Classe.BDR
    if t.endswith("11"):
        return Classe.FII  # palpite: a maioria dos "11" é FII — ETF corrige no cadastro
    if len(t) == 5 and t[4] in "3456":
        return Classe.ACAO

    return Classe.RENDA_FIXA
