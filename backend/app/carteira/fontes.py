"""As fontes de carteira.

FINCONTROL — a que já funciona. Todo o trabalho difícil está em `ingest/fincontrol.py`,
inclusive o bug de data que quase envenenou tudo (o FinControl grava em DOIS formatos
misturados, e um parser ingênuo ou descarta 80% das transações em silêncio, ou embaralha as
datas e cria cotas fantasma).

MANUAL — a posição vem digitada, direto do banco. É o mínimo para um usuário novo existir sem
integração nenhuma.
"""

from __future__ import annotations

from app.carteira.base import Carteira, Fonte, FonteDeCarteira, Posicao


class FinControl(FonteDeCarteira):
    fonte = Fonte.FINCONTROL

    def campos_config(self) -> dict[str, str]:
        return {
            "url": "URL do FinControl",
            "usuario": "usuário ou e-mail",
            "senha": "senha",
        }

    def puxar(self, config: dict) -> Carteira:
        from app.ingest import fincontrol as fc

        c = fc.puxar(
            url=config.get("url"),
            usuario=config.get("usuario"),
            senha=config.get("senha"),
        )
        return Carteira(
            posicoes=[
                Posicao(p.ticker, p.quantidade, p.custo_medio, _classe(p.categoria))
                for p in c.posicoes
            ],
            fonte=self.fonte,
            recebidos=c.recebidos,
            a_receber=c.a_receber,
            vendas_do_mes=fc.vendas_no_mes(c),
        )

    def validar(self, config: dict) -> str | None:
        if erro := super().validar(config):
            return erro
        try:
            self.puxar(config)
        except Exception as e:  # noqa: BLE001 — a mensagem da fonte é o que interessa
            return str(e)
        return None


class Manual(FonteDeCarteira):
    """Posições digitadas. O usuário mantém; o sistema só lê do banco."""

    fonte = Fonte.MANUAL

    def campos_config(self) -> dict[str, str]:
        return {}  # nada a configurar

    def puxar(self, config: dict) -> Carteira:
        # As posições vêm da tabela `posicoes` — quem as carrega é o repositório, que conhece
        # o user_id. A fonte MANUAL não busca nada em lugar nenhum.
        return Carteira(posicoes=[], fonte=self.fonte)


# A categoria que a fonte reporta ('Ações', 'Fundos Imobiliários', 'BDRs'…) vira a classe
# canônica do sistema. Fonte nova traduz aqui, e nada mais muda.
_MAPA = {
    "aç": "ACAO", "ac": "ACAO", "açõ": "ACAO",
    "fund": "FII", "fii": "FII",
    "etf": "ETF",
    "bdr": "BDR",
    "cript": "CRIPTO",
    "renda": "RENDA_FIXA",
}


def _classe(categoria: str | None) -> str | None:
    if not categoria:
        return None
    c = categoria.strip().lower()
    for chave, classe in _MAPA.items():
        if c.startswith(chave):
            return classe
    return None
