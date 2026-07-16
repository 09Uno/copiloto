"""O briefing diário — o mesmo veredito do painel, condensado para o WhatsApp.

Segue a disciplina do vigia: **começa pelo que pede decisão e cala quando está tudo de pé.**
Um resumo que repete "tudo ok" todo dia vira ruído que você aprende a ignorar; um que lidera
com "o payout da TAEE3 furou 100%" você lê. Por isso a ordem é a da urgência, não a alfabética.

Não decide nada. Ele condensa os fatos e devolve a pergunta — igual ao resto do sistema.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.api import avaliador, repo
from app.api.pool import pool
from app.ativos.decisao import Zona, ZonaCompra, zona_de_compra
from app.tese import motor as tm


@dataclass
class ItemTese:
    ticker: str
    veredito: tm.Veredito
    tenho: bool
    zona: ZonaCompra | None


async def coletar(user_id) -> tuple[list[ItemTese], list[repo.Posicao]]:
    """Calcula o veredito de cada tese ativa — mesma lógica de `checar_todas`, reaproveitada."""
    margem = await repo.margem_seguranca(user_id)
    carteira = await repo.tickers_carteira(user_id)
    posicoes = await repo.posicoes(user_id)

    itens: list[ItemTese] = []
    async with pool().acquire() as c:
        teses = await c.fetch(
            "SELECT id, ticker, resumo, meta_yield FROM teses "
            "WHERE user_id = $1 AND encerrada_em IS NULL ORDER BY criada_em",
            user_id,
        )
        for t in teses:
            ps = await c.fetch(
                "SELECT id, metrica, operador, limite, valor_na_criacao, qualitativo, "
                "descricao, prazo FROM tese_pilares WHERE tese_id = $1 ORDER BY id",
                t["id"],
            )
            pilares = [
                tm.Pilar(
                    id=p["id"], metrica=p["metrica"], operador=p["operador"],
                    limite=float(p["limite"]) if p["limite"] is not None else None,
                    valor_na_criacao=(float(p["valor_na_criacao"])
                                      if p["valor_na_criacao"] is not None else None),
                    qualitativo=p["qualitativo"], descricao=p["descricao"], prazo=p["prazo"],
                )
                for p in ps
            ]
            meta = float(t["meta_yield"]) if t["meta_yield"] else 0.06
            av = avaliador.avaliar(t["ticker"], meta)
            v = tm.verificar(av, t["resumo"], pilares)
            itens.append(ItemTese(t["ticker"], v, t["ticker"] in carteira,
                                  zona_de_compra(av, margem)))
    return itens, posicoes


def _meses_ate(prazo: date, hoje: date) -> int:
    return max(0, (prazo.year - hoje.year) * 12 + (prazo.month - hoje.month))


def formatar(itens: list[ItemTese], posicoes: list[repo.Posicao], hoje: date) -> tuple[str, bool]:
    """Monta o texto do WhatsApp (negrito com *asterisco*). Devolve (texto, tem_alertas)."""
    # baldes de atenção — a MESMA lógica da tela "Hoje"
    precisa = [i for i in itens if i.tenho and (i.veredito.cairam or i.veredito.apostas_perdidas)]
    zona = [
        i for i in itens
        if i.zona and i.zona.estado is Zona.COMPRA
        and not i.veredito.cairam and not i.veredito.apostas_perdidas
    ]
    apostas = [i for i in itens if i.veredito.apostas_em_curso and not i.veredito.cairam]
    com_tese = {i.ticker for i in itens}
    sem_tese = [p.ticker for p in posicoes if p.ticker not in com_tese]

    L: list[str] = [f"📊 *Copiloto — {hoje:%d/%m}*"]

    if precisa:
        L.append("")
        L.append(f"⚠️ *Precisa de você ({len(precisa)})*")
        for i in precisa:
            quebrou = i.veredito.cairam + i.veredito.apostas_perdidas
            motivos = "; ".join(str(r.pilar) for r in quebrou)
            L.append(f"• *{i.ticker}* — caiu: {motivos}")

    if zona:
        L.append("")
        L.append(f"🟢 *Na sua zona de compra ({len(zona)})*")
        for i in zona:
            alvo = f"alvo ≤ R$ {i.zona.preco_compra:.2f}".replace(".", ",")
            preco = f"R$ {i.zona.preco:.2f}".replace(".", ",") if i.zona.preco else "—"
            marca = "" if i.tenho else " _(de olho)_"
            L.append(f"• *{i.ticker}* {preco} ({alvo}) — "
                     f"{i.veredito.de_pe}/{i.veredito.total_verificaveis} pilares{marca}")

    if apostas:
        L.append("")
        L.append(f"⏳ *Apostas correndo ({len(apostas)})*")
        for i in apostas:
            r = i.veredito.apostas_em_curso[0]
            meses = _meses_ate(r.pilar.prazo, hoje) if r.pilar.prazo else 0
            L.append(f"• *{i.ticker}* — {r.pilar} (faltam {meses}m)")

    if sem_tese:
        L.append("")
        L.append(f"📝 *Sem tese ({len(sem_tese)}):* {', '.join(sem_tese)}")

    tem_alertas = bool(precisa or zona)
    if not precisa and not zona and not apostas:
        L.append("")
        de_pe = sum(1 for i in itens if i.veredito.intacta)
        L.append(f"✅ Tudo tranquilo — nenhum pilar caiu. {de_pe} teses de pé.")
    else:
        L.append("")
        L.append("_Os fatos estão aqui; a decisão é sua._")

    return "\n".join(L), tem_alertas


async def montar_texto(user_id, hoje: date | None = None) -> tuple[str, bool]:
    itens, posicoes = await coletar(user_id)
    return formatar(itens, posicoes, hoje or date.today())
