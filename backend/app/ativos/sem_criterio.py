"""As classes que **não têm critério de valor** — e admitem isso.

Este arquivo é uma decisão de projeto, não uma lacuna.

O Bitcoin não tem lucro, não tem patrimônio, não paga dividendo. **Não existe preço teto para
ele.** Um ETF de índice também não tem tese própria — ele *é* o benchmark; "avaliar" o BOVA11 é
avaliar a bolsa inteira.

Seria trivial inventar um número aqui — um "score de 0 a 100", uma média móvel, um RSI — e a
tela ficaria mais bonita. **Seria a mesma mentira que passamos dois dias destruindo:** o
backtest mostrou AUC 0,50 no preço e na notícia, e o histórico diz ~47% de acerto para qualquer
setup. Um score fabricado daria **convicção sem vantagem** — a combinação que mais destrói
patrimônio, porque faz operar mais.

Então estas classes respondem, na tela, com todas as letras: **"não sei dizer se está caro."**

O que o sistema PODE fazer com elas — e é o que de fato importa — é o que não exige previsão:
alocação, concentração e a sua própria regra ("aportar em BTC só na queda").
"""

from __future__ import annotations

from app.ativos.base import Avaliacao, Classe, ClasseDeAtivo


class Cripto(ClasseDeAtivo):
    classe = Classe.CRIPTO

    def metricas_disponiveis(self) -> dict[str, str]:
        return {}  # nenhuma. E isto é uma resposta, não um buraco.

    def avaliar(self, ticker: str, preco: float | None, meta_yield: float) -> Avaliacao:
        return Avaliacao(
            ticker=ticker, classe=self.classe, preco=preco, metricas={}, teto=None,
            sem_criterio=(
                "cripto não tem lucro, patrimônio nem dividendo — não existe preço teto. "
                "O sistema não vai inventar um número para preencher a tela. "
                "O que dá para decidir aqui é ALOCAÇÃO (quanto), não PREÇO (quando)."
            ),
        )


class ETF(ClasseDeAtivo):
    classe = Classe.ETF

    def metricas_disponiveis(self) -> dict[str, str]:
        return {}

    def avaliar(self, ticker: str, preco: float | None, meta_yield: float) -> Avaliacao:
        return Avaliacao(
            ticker=ticker, classe=self.classe, preco=preco, metricas={}, teto=None,
            sem_criterio=(
                "ETF de índice não tem tese própria — ele É o benchmark. "
                "A decisão aqui é de ALOCAÇÃO, não de valuation. "
                "(E o backtest mostrou que comprar o índice inteiro bateu todas as "
                "estratégias que testamos, com metade do drawdown.)"
            ),
        )


class BDR(ClasseDeAtivo):
    classe = Classe.BDR

    def metricas_disponiveis(self) -> dict[str, str]:
        return {}  # o balanço está na SEC, não na CVM — sem a ponte, nada a verificar

    def avaliar(self, ticker: str, preco: float | None, meta_yield: float) -> Avaliacao:
        return Avaliacao(
            ticker=ticker, classe=self.classe, preco=preco, metricas={}, teto=None,
            sem_criterio=(
                "BDR espelha uma empresa de fora (ROXO34 = Nubank). O balanço está na SEC, "
                "não na CVM — sem essa ponte, o sistema não tem fundamento para checar. "
                "A tese pode ser registrada como qualitativa; a checagem por número fica para "
                "quando a ingestão da SEC existir."
            ),
        )


class RendaFixa(ClasseDeAtivo):
    classe = Classe.RENDA_FIXA

    def metricas_disponiveis(self) -> dict[str, str]:
        return {}  # até o módulo próprio existir (taxa vs CDI/IPCA, prazo, risco de crédito)

    def avaliar(self, ticker: str, preco: float | None, meta_yield: float) -> Avaliacao:
        return Avaliacao(
            ticker=ticker, classe=self.classe, preco=preco, metricas={}, teto=None,
            sem_criterio=(
                "renda fixa se avalia por taxa contratada vs. CDI/IPCA, prazo e risco de "
                "crédito — não por preço teto. Módulo próprio, ainda não construído."
            ),
        )
