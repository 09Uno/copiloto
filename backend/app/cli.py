"""CLI do motor.

    dands backfill --anos 3          # baixa o histórico da watchlist
    dands backfill --market CRYPTO   # só cripto
    dands doctor                     # relatório de cobertura e gaps
    dands show BTCUSDT 15m           # espia a série

    dands db init                    # aplica o schema no Supabase
    dands db load                    # carrega o Parquet no Postgres
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pandas as pd
import typer
from rich.console import Console
from rich.table import Table

from app.core.config import Asset, Market, Timeframe, load_params, watchlist
from app.ingest import binance, gaps, store, yahoo

app = typer.Typer(add_completion=False, help="Motor quantamental — uso próprio")
db_app = typer.Typer(help="Postgres (Supabase) — camada de serviço da API.")
app.add_typer(db_app, name="db")
console = Console()


def _fetch(asset: Asset, tf: Timeframe, inicio: datetime):
    """Roteia o ativo para o conector do seu mercado."""
    if asset.market is Market.CRYPTO:
        return binance.fetch_klines(asset, tf, inicio)
    return yahoo.fetch(asset, tf, inicio)


@app.command()
def backfill(
    anos: float = typer.Option(3.0, help="Profundidade do histórico, em anos."),
    market: Market | None = typer.Option(None, help="Restringe a um mercado."),
    full: bool = typer.Option(
        False, "--full", help="Rebaixa tudo, ignorando o que já está no disco."
    ),
) -> None:
    """Baixa o histórico. Idempotente: rodar de novo só busca o que falta."""
    horizonte = datetime.now(UTC) - timedelta(days=365 * anos)
    ativos = watchlist(market)

    console.print(
        f"[bold]Backfill[/bold] · {len(ativos)} ativos · "
        f"desde {horizonte:%Y-%m-%d}{' · FULL' if full else ' · incremental'}\n"
    )

    total = 0
    for asset in ativos:
        for tf in asset.timeframes:
            inicio = horizonte
            if not full and (janela := store.span(asset, tf)):
                primeiro, ultimo = janela
                # Se a série já começa DEPOIS do horizonte pedido, o histórico precisa ser
                # estendido para TRÁS — retomar da última vela só avançaria para a frente e
                # a série ficaria eternamente curta. (Foi assim que os 7 tickers originais
                # continuaram com 3 anos enquanto os novos vinham com 20.)
                margem = timedelta(days=7)
                if primeiro <= horizonte + margem:
                    # Retoma da última vela (e não da seguinte): reescrevê-la é barato e
                    # cobre o caso de ela ter sido gravada ainda em formação.
                    inicio = max(horizonte, ultimo.to_pydatetime())

            try:
                df = _fetch(asset, tf, inicio)
                novas = store.upsert(asset, tf, df)
            except Exception as exc:  # noqa: BLE001 — fonte instável não derruba o lote
                console.print(f"  [red]![/red] {asset.ticker} {tf.value}: {exc}")
                continue

            total += novas
            marca = "[green]+[/green]" if novas else "[dim]=[/dim]"
            console.print(
                f"  {marca} {asset.ticker:<10} {tf.value:<4} "
                f"[dim]{novas} novas · {len(store.read(asset, tf))} no total[/dim]"
            )

    console.print(f"\n[bold green]{total}[/bold green] velas novas.")


@app.command()
def doctor(market: Market | None = typer.Option(None)) -> None:
    """Relatório de cobertura e gaps. Rodar ANTES de confiar no dado."""
    tabela = Table(title="Cobertura do histórico")
    for col in ("Ativo", "TF", "Velas", "Início", "Fim", "Cobertura", "Gaps"):
        tabela.add_column(col)

    sujos = 0
    for asset in watchlist(market):
        for tf in asset.timeframes:
            r = gaps.detect(asset, tf)
            if r.n_velas == 0:
                tabela.add_row(asset.ticker, tf.value, "[red]0[/red]", "—", "—", "—", "—")
                sujos += 1
                continue

            n = len(r.faltando)
            if not n:
                cor, nota = "green", "0"
            elif r.exato:
                cor, nota = "red", str(n)
                sujos += 1
            else:
                # Ação: dia útil ausente é quase sempre feriado, não corrupção.
                cor, nota = "yellow", f"{n}?"

            tabela.add_row(
                asset.ticker,
                tf.value,
                str(r.n_velas),
                f"{r.inicio:%Y-%m-%d}",
                f"{r.fim:%Y-%m-%d}",
                f"[{cor}]{r.cobertura_pct:.1f}%[/{cor}]",
                f"[{cor}]{nota}[/{cor}]",
            )

    console.print(tabela)
    console.print(
        "[dim]Cripto: grade exata, todo gap é real (vermelho).\n"
        "Ação: dia útil ausente é CANDIDATO a gap (amarelo) — normalmente feriado.[/dim]"
    )
    if sujos:
        console.print(f"\n[bold red]{sujos} série(s) com problema real.[/bold red]")
    else:
        console.print("\n[bold green]Histórico íntegro.[/bold green]")


@app.command()
def show(ticker: str, timeframe: str = "1d", n: int = 10) -> None:
    """Últimas N velas de uma série."""
    asset = next((a for a in watchlist() if a.ticker == ticker), None)
    if asset is None:
        raise typer.BadParameter(f"{ticker} não está na watchlist (app/core/config.py)")

    df = store.read(asset, Timeframe(timeframe))
    if df.empty:
        console.print("[yellow]Série vazia. Rode `dands backfill`.[/yellow]")
        raise typer.Exit(1)

    console.print(f"[bold]{asset.ticker}[/bold] {timeframe} · {len(df)} velas")
    console.print(df.tail(n).to_string(index=False))


@app.command()
def cotahist_b3(
    anos: int = typer.Option(20, help="Profundidade, em anos."),
) -> None:
    """Ingere a B3 pela série histórica OFICIAL (COTAHIST), com ajuste de evento corporativo.

    Substitui o Yahoo como fonte da B3. Duas razões:
      · o Yahoo mente ("possibly delisted" para a Embraer) e não tem SLA;
      · o COTAHIST traz TODO papel que negociou — inclusive os que morreram, que é o que
        conserta o viés de sobrevivência do backtest.

    O preço do COTAHIST é BRUTO. Sem o ajuste por bonificação/desdobramento, o BBAS3 exibiria
    um "crash de -50%" fantasma no dia do split, e o motor dispararia uma compra enorme e falsa.
    """
    import pandas as pd

    from app.ingest import corporate, cotahist

    ano_fim = datetime.now(UTC).year
    lista = list(range(ano_fim - anos + 1, ano_fim + 1))

    console.print(f"[bold]COTAHIST[/bold] · {lista[0]}–{lista[-1]}\n[dim]baixando…[/dim]")
    bruto = cotahist.load(lista)
    if bruto.empty:
        console.print("[red]nada baixado[/red]")
        raise typer.Exit(1)

    console.print(
        f"[dim]{len(bruto):,} registros · {bruto['ticker'].nunique():,} tickers na bolsa[/dim]\n"
    )

    por_ticker = {t: g for t, g in bruto.groupby("ticker")}
    total, ajustados, reconciliados, alarmes = 0, 0, 0, []

    for asset in watchlist(Market.B3):
        base = asset.ticker.removesuffix(".SA")
        g = por_ticker.get(base)
        if g is None or g.empty:
            console.print(f"  [red]![/red] {base}: ausente no COTAHIST")
            continue

        g = g.sort_values("timestamp").reset_index(drop=True)
        eventos = corporate.splits(asset.ticker)
        df = corporate.adjust(g, eventos)

        # A lista de splits do Yahoo é inconsistente com o preço DELE MESMO (o MGLU3 tinha um
        # evento de 6,9% em 2024 que ele aplica no preço mas não declara). Um degrau na razão
        # entre as duas séries denuncia o evento omitido — e um buraco de 6,9% não dispara o
        # alarme de 25%, mas é um falso movimento de 1-2σ.
        ref = yahoo.close_series(asset)
        if (faltantes := corporate.reconcile(df, ref)) is not None and len(faltantes):
            eventos = pd.concat([eventos, faltantes]).sort_index()
            df = corporate.adjust(g, eventos)
            reconciliados += len(faltantes)

        if len(eventos):
            ajustados += 1

        suspeitos = corporate.jumps_nao_explicados(df, eventos)
        if len(suspeitos):
            alarmes.append((base, len(suspeitos)))

        # Troca de fonte: o Yahoo carimbava 03:00 UTC, o COTAHIST 00:00. Sem apagar,
        # cada pregão viraria DUAS velas e o motor calcularia sobre uma série dobrada.
        store.purge(asset, Timeframe.D1)
        total += store.upsert(asset, Timeframe.D1, df)

    console.print(
        f"\n[bold green]{total:,}[/bold green] velas · "
        f"[dim]{ajustados} ativos com evento corporativo ajustado · "
        f"{reconciliados} eventos que o Yahoo OMITIA, recuperados pelo degrau da razão[/dim]"
    )
    if alarmes:
        console.print(
            "\n[yellow]Saltos NÃO explicados por evento conhecido "
            "(evento corporativo que o Yahoo não conhece, ou notícia real):[/yellow]"
        )
        for tk, n in sorted(alarmes, key=lambda x: -x[1])[:15]:
            console.print(f"  {tk}: {n}")


def _linha_metricas(m, rotulo: str) -> list[str]:
    if m is None or m.n == 0:
        return [rotulo, "—", "—", "—", "—", "—", "—", "—"]
    cor = "green" if m.tem_borda else "red"
    return [
        rotulo,
        str(m.n),
        f"{m.taxa_acerto:.0f}%",
        f"[{cor}]{m.expectancia_r:+.3f}R[/{cor}]",
        f"{m.profit_factor:.2f}",
        f"{m.cagr_pct:+.1f}%",
        f"{m.max_drawdown_pct:.1f}%",
        f"{m.sharpe:.2f}",
    ]


@app.command()
def backtest(
    estrategia: str = typer.Argument("MEAN_REV", help="MEAN_REV ou XSECT."),
    market: Market = typer.Option(Market.CRYPTO),
    timeframe: str = typer.Option("15m"),
) -> None:
    """FASE 2 — o portão de decisão. Há borda líquida de custos FORA da amostra?

    Um resultado bom dentro da amostra não significa nada: com parâmetros suficientes dá para
    ajustar qualquer curva ao passado. Só o out-of-sample tem voto.
    """
    from backtest import runner

    tf = Timeframe(timeframe)
    p = load_params(market, tf)

    console.print(
        f"\n[bold]{estrategia}[/bold] · {market.value} {tf.value} · "
        f"engine {p.engine_version}\n[dim]custos: {p.custos.ida_e_volta(market):.2f}% ida e "
        f"volta · risco 1%/operação · entrada na ABERTURA seguinte[/dim]\n"
    )

    e = estrategia.upper()
    if e == "XSECT":
        r = runner.cross_sectional(p, market, tf)
    elif e in ("MOM", "MOMENTUM"):
        r = runner.momentum(p, market, tf)
    else:
        r = runner.mean_rev(p, market, tf)

    if r.trades.empty:
        console.print("[yellow]nenhum trade gerado[/yellow]")
        raise typer.Exit(1)

    t = Table("Amostra", "Trades", "Acerto", "Expectância", "P.Factor", "CAGR", "Max DD",
              "Sharpe")
    t.add_row(*_linha_metricas(r.dentro, "dentro (calibra)"))
    t.add_row(*_linha_metricas(r.fora, "[bold]FORA (julga)[/bold]"))
    console.print(t)

    if r.fora:
        f = r.fora
        console.print(
            f"[dim]fora da amostra: {f.periodo} · TP {f.tp} / SL {f.sl} / TIMEOUT "
            f"{f.timeout} · ganho médio {f.ganho_medio_r:+.2f}R · perda média "
            f"{f.perda_media_r:+.2f}R[/dim]"
        )
        # Significância: sem isto, ruído com média positiva vira "borda" — e é assim que se
        # acaba operando sorte com dinheiro de verdade.
        sig = "[green]significante[/green]" if f.significante else "[red]RUÍDO[/red]"
        console.print(
            f"[dim]expectância {f.expectancia_r:+.3f}R · t = {f.t_stat:.2f} → {sig}[/dim]"
        )
        if f.buy_hold_cagr_pct is not None:
            bh = "[green]bate[/green]" if f.bate_buy_hold else "[red]PERDE PARA[/red]"
            console.print(
                f"[dim]buy & hold no período: {f.buy_hold_cagr_pct:+.1f}% a.a. → a "
                f"estratégia {bh} o buy & hold[/dim]"
            )

    cor = "green" if r.veredito == "TEM BORDA" else "red"
    console.print(f"\n  VEREDITO (out-of-sample): [bold {cor}]{r.veredito}[/bold {cor}]\n")


@app.command()
def sentimento(
    ano_ini: int = typer.Option(2017),
    ano_fim: int = typer.Option(2026),
) -> None:
    """Coleta o tom diário da imprensa (GDELT) — a última hipótese não testada.

    O preço já foi reprovado: AUC ~0,50 fora da amostra. A tese quantamental original diz que
    o TEXTO carrega informação que o preço não tem. Aqui coletamos o dado para MEDIR isso.
    """
    from app.core.gdelt_map import CONSULTAS
    from app.ingest import gdelt

    console.print(
        f"[bold]GDELT[/bold] · {len(CONSULTAS)} empresas · {ano_ini}–{ano_fim}\n"
        "[dim]só papéis com cobertura real de imprensa — papel sem notícia não tem "
        "sentimento a medir[/dim]\n"
    )

    ok, vazios = 0, []
    for tk in CONSULTAS:
        df = gdelt.fetch(tk, ano_ini, ano_fim)
        if df.empty:
            vazios.append(tk)
            console.print(f"  [red]![/red] {tk.removesuffix('.SA')}: sem dado")
            continue
        ok += 1
        art = df["n_artigos"].sum()
        console.print(
            f"  [green]+[/green] {tk.removesuffix('.SA'):<8} "
            f"[dim]{len(df):>5} dias · {art:>9,.0f} artigos · "
            f"tom médio {df['tom'].mean():+.2f}[/dim]"
        )

    console.print(f"\n[bold green]{ok}[/bold green] empresas com série de tom.")
    if vazios:
        console.print(f"[dim]sem cobertura: {', '.join(v.removesuffix('.SA') for v in vazios)}[/dim]")


@app.command()
def informacao(
    horizonte: int = typer.Option(10, help="Pregões à frente."),
    corte: str = typer.Option("2019-12-31", help="Fim do in-sample."),
) -> None:
    """As features CARREGAM INFORMAÇÃO? (a pergunta que o backtest de lucro não responde)

    Se o decil de cima terminar bem mais vezes que o de baixo, existe informação — e a
    probabilidade que a ferramenta mostrar é honesta. Se todos derem ~50%, qualquer "68% de
    chance" na tela seria mentira com cara de ciência. É também o portão do ML: sem sinal para
    aprender, nenhum modelo inventa um.
    """
    from app.core import b3_universe
    from backtest import information

    p = load_params(Market.B3, Timeframe.D1)
    painel, _ = b3_universe.load()

    console.print("[dim]calculando features de 373 papéis…[/dim]")
    f = information.painel_features(painel, p)
    lim = pd.Timestamp(corte, tz="UTC")

    features = [
        ("deviation_from_mean", "distância da média (σ)"),
        ("volume_z_score", "z-score do volume"),
        ("regression_slope", "inclinação (log-preço)"),
        ("regression_r2", "nitidez da tendência (R²)"),
        ("atr_pct", "volatilidade (ATR/preço)"),
    ]

    console.print(
        f"\n[bold]Discriminação[/bold] · retorno {horizonte} pregões à frente · "
        f"{len(f):,} observações\n"
    )

    t = Table("Feature", "AUC dentro", "AUC FORA", "Spread FORA", "Veredito")
    for col, nome in features:
        dentro = information.avaliar(f[f["timestamp"] <= lim], col, horizonte)
        fora = information.avaliar(f[f["timestamp"] > lim], col, horizonte)
        if dentro is None or fora is None:
            continue

        # Só vale se discriminar FORA da amostra — e no mesmo sentido de dentro.
        mesmo_sinal = (dentro.auc - 0.5) * (fora.auc - 0.5) > 0
        vale = fora.informativa and mesmo_sinal
        cor = "green" if vale else "dim"

        t.add_row(
            nome,
            f"{dentro.auc:.3f}",
            f"[{cor}]{fora.auc:.3f}[/{cor}]",
            f"{fora.spread:+.2f} p.p.",
            f"[{cor}]{'INFORMA' if vale else 'ruído'}[/{cor}]",
        )
    console.print(t)
    console.print(
        "[dim]AUC 0.500 = moeda honesta. Acima de 0.53 já é informação real e rara em "
        "finanças.\nSpread = retorno médio do decil de cima menos o do decil de baixo.[/dim]"
    )

    # A tabela de calibração da feature central da tese: a distância da média.
    fora = information.avaliar(f[f["timestamp"] > lim], "deviation_from_mean", horizonte)
    if fora:
        console.print(
            "\n[bold]Calibração da tese central[/bold] (distância da média, FORA da amostra)\n"
            "[dim]a tese diz: quanto MAIS NEGATIVO o desvio, MAIS o papel deveria subir "
            "depois[/dim]"
        )
        c = Table("Decil", "Faixa (σ)", "n", "% que subiu", f"Retorno médio ({horizonte}d)")
        for _, r in fora.tabela.iterrows():
            c.add_row(
                str(int(r["decil"]) + 1),
                f"{r['faixa_min']:+.2f} a {r['faixa_max']:+.2f}",
                f"{int(r['n']):,}",
                f"{r['taxa_alta']:.1f}%",
                f"{r['retorno_medio']:+.2f}%",
            )
        console.print(c)


@app.command()
def info_sentimento(
    horizonte: int = typer.Option(10, help="Pregões à frente."),
    corte: str = typer.Option("2022-12-31", help="Fim do in-sample."),
) -> None:
    """O TEXTO carrega informação que o preço não tem? (a tese original do projeto)

    Mesmo teste que reprovou o preço — AUC e calibração por decil, fora da amostra. Mudar a
    régua entre um candidato e outro é a forma mais fácil de aprovar o que se quer aprovar.
    """
    from app.core import b3_universe
    from app.ingest import gdelt
    from backtest import information, sentiment_test

    tom = gdelt.load_todos()
    if tom.empty:
        console.print("[yellow]sem dado do GDELT. Rode `dands sentimento` antes.[/yellow]")
        raise typer.Exit(1)

    painel, _ = b3_universe.load()
    m = sentiment_test.montar(painel, tom)
    if m.empty:
        console.print("[red]nenhuma sobreposição entre preço e notícia[/red]")
        raise typer.Exit(1)

    lim = pd.Timestamp(corte, tz="UTC")
    console.print(
        f"\n[bold]O texto informa?[/bold] · retorno {horizonte} pregões à frente\n"
        f"[dim]{len(m):,} dias-papel · {m['ticker'].nunique()} empresas · "
        f"{m['n_artigos'].sum():,.0f} artigos[/dim]\n"
    )

    t = Table("Feature de texto", "n FORA", "AUC dentro", "AUC FORA", "Spread FORA", "Veredito")
    achou = False
    for col, nome in sentiment_test.FEATURES:
        dentro = information.avaliar(m[m["dia"] <= lim], col, horizonte)
        fora = information.avaliar(m[m["dia"] > lim], col, horizonte)
        if dentro is None or fora is None:
            t.add_row(nome, "—", "—", "—", "—", "[dim]sem amostra[/dim]")
            continue

        mesmo_sinal = (dentro.auc - 0.5) * (fora.auc - 0.5) > 0
        vale = fora.informativa and mesmo_sinal
        achou |= vale
        cor = "green" if vale else "dim"

        t.add_row(
            nome, f"{fora.n:,}",
            f"{dentro.auc:.3f}",
            f"[{cor}]{fora.auc:.3f}[/{cor}]",
            f"{fora.spread:+.2f} p.p.",
            f"[{cor}]{'INFORMA' if vale else 'ruído'}[/{cor}]",
        )
    console.print(t)
    console.print(
        "[dim]AUC 0.500 = cara ou coroa. Preço deu 0.487–0.515 fora da amostra.[/dim]"
    )

    melhor = "tom_z"
    fora = information.avaliar(m[m["dia"] > lim], melhor, horizonte)
    if fora:
        console.print(
            f"\n[bold]Calibração[/bold] · tom vs. a própria história (FORA da amostra)\n"
            "[dim]a tese diz: tom MAIS NEGATIVO deveria vir antes de queda; "
            "tom positivo, antes de alta[/dim]"
        )
        c = Table("Decil", "Faixa (z)", "n", "% que subiu", f"Retorno médio ({horizonte}d)")
        for _, r in fora.tabela.iterrows():
            c.add_row(
                str(int(r["decil"]) + 1),
                f"{r['faixa_min']:+.2f} a {r['faixa_max']:+.2f}",
                f"{int(r['n']):,}",
                f"{r['taxa_alta']:.1f}%",
                f"{r['retorno_medio']:+.2f}%",
            )
        console.print(c)

    cor = "green" if achou else "red"
    veredito = "O TEXTO INFORMA" if achou else "O TEXTO TAMBÉM NÃO INFORMA"
    console.print(f"\n  VEREDITO: [bold {cor}]{veredito}[/bold {cor}]\n")


@app.command()
def carteira(
    market: Market = typer.Option(Market.B3),
    corte: str = typer.Option("2019-12-31", help="Fim do in-sample."),
) -> None:
    """Momentum como CARTEIRA — compra os vencedores, SEGURA, sem stop. Bate o índice?

    É a forma em que a tese é de fato afirmada (Jegadeesh & Titman), e a que corresponde ao
    que um investidor faz. O teste anterior usava stop loss — e estopou 291 dos 843 trades,
    expulsando a posição por quedas temporárias que uma carteira simplesmente aguentaria.
    """
    from backtest import portfolio

    p = load_params(market, Timeframe.D1)
    console.print(
        f"\n[bold]Carteira Momentum 12-1[/bold] · {market.value} · "
        f"{p.momentum.n_extremos} papéis · rebalanceamento mensal · [bold]sem stop[/bold]"
    )

    mom, bench = portfolio.rodar(p, market)
    lim = pd.Timestamp(corte, tz="UTC")

    for rotulo, ate in (("DENTRO da amostra", True), ("FORA da amostra", False)):
        a = portfolio.fatiar(mom, lim)[0 if ate else 1]
        b = portfolio.fatiar(bench, lim)[0 if ate else 1]
        if len(a.retornos) < 12:
            continue

        venceu = a.cagr > b.cagr
        cor = "green" if venceu else "red"
        console.print(f"\n[bold]{rotulo}[/bold] [dim]({len(a.retornos)} meses)[/dim]")

        t = Table("Carteira", "CAGR", "Vol", "Sharpe", "Max DD")
        for c, destaque in ((a, True), (b, False)):
            nome = f"[{cor}]{c.nome}[/{cor}]" if destaque else f"[dim]{c.nome}[/dim]"
            t.add_row(nome, f"{c.cagr:+.1f}%", f"{c.vol:.1f}%", f"{c.sharpe:.2f}",
                      f"{c.max_dd:.1f}%")
        console.print(t)

        console.print(
            f"  [{cor}]{'BATE' if venceu else 'PERDE PARA'} o universo[/{cor}] "
            f"[dim]por {a.cagr - b.cagr:+.1f} p.p. ao ano[/dim]"
        )

    console.print(
        "\n[dim]Benchmark = universo igualmente ponderado: MESMA base de preço (sem "
        "dividendo) e mesmo custo de giro.\nComparar com o Ibovespa seria injusto contra "
        "nós — ele é índice de RETORNO TOTAL, reinveste dividendos.[/dim]\n"
    )


@app.command()
def calibrar(
    estrategia: str = typer.Argument("XSECT"),
    market: Market = typer.Option(Market.B3),
    timeframe: str = typer.Option("1d"),
) -> None:
    """Grid search — calibra NO IN-SAMPLE e só depois abre o out-of-sample.

    Escolher o melhor pelo out-of-sample é a fraude mais comum do backtest: com combinações
    suficientes, a sorte produz uma que parece genial no período de teste, e o out-of-sample
    vira mais um conjunto de treino.
    """
    from backtest import grid, runner

    tf = Timeframe(timeframe)
    p = load_params(market, tf)

    if estrategia.upper() == "XSECT":
        espaco = {
            "risco.stop_atr_mult": [1.5, 2.5, 3.5],       # o stop apertado é suspeito nº1
            "risco.rr_minimo": [1.0, 1.5, 2.0],
            "cross_sectional.janela_reversao": [3, 5, 10],
            "cross_sectional.n_extremos": [5, 10, 20],
        }
        # Indicadores não dependem de nenhum parâmetro do grid: computa-se UMA vez.
        console.print("[dim]pré-computando indicadores dos 373 papéis…[/dim]")
        cache = runner.cache_xsect(p)
        executar = lambda pp: runner.cross_sectional(pp, market, tf, cache)  # noqa: E731
    else:
        espaco = {
            "bandas.n_sigma_entrada": [2.0, 2.5, 3.0],
            "volume.z_minimo": [1.0, 2.0],
            "risco.stop_atr_mult": [1.5, 2.5],
            "regime.r2_max_lateral": [0.2, 0.3, 0.5],
        }
        executar = lambda pp: runner.mean_rev(pp, market, tf)  # noqa: E731

    n = 1
    for v in espaco.values():
        n *= len(v)
    console.print(
        f"\n[bold]Calibrando {estrategia}[/bold] · {market.value} {tf.value} · "
        f"{n} combinações\n[dim]a escolha olha SÓ o in-sample[/dim]\n"
    )

    pontos = grid.rodar(p, espaco, executar)
    if not pontos:
        console.print("[red]nenhuma combinação produziu trades[/red]")
        raise typer.Exit(1)

    console.print(grid.tabela(pontos).to_string(index=False))

    melhor = grid.melhor_in_sample(pontos)
    if melhor is None:
        console.print("\n[yellow]nenhuma combinação com trades suficientes[/yellow]")
        raise typer.Exit(1)

    console.print(f"\n[bold]Escolhido pelo in-sample:[/bold] {melhor.config}")
    console.print(
        f"  in-sample:  {melhor.dentro.n} trades · "
        f"expectância {melhor.dentro.expectancia_r:+.3f}R · PF {melhor.dentro.profit_factor:.2f}"
    )

    if melhor.fora is None or melhor.fora.n < 30:
        console.print("\n[yellow]out-of-sample sem amostra suficiente[/yellow]")
        raise typer.Exit(1)

    f = melhor.fora
    cor = "green" if f.tem_borda else "red"
    console.print(
        f"  [bold]OUT-OF-SAMPLE:[/bold] {f.n} trades · "
        f"[{cor}]expectância {f.expectancia_r:+.3f}R[/{cor}] · PF {f.profit_factor:.2f} · "
        f"acerto {f.taxa_acerto:.0f}% · CAGR {f.cagr_pct:+.1f}% · DD {f.max_drawdown_pct:.0f}%"
    )
    console.print(
        f"\n  VEREDITO: [bold {cor}]"
        f"{'TEM BORDA' if f.tem_borda else 'SEM BORDA'}[/bold {cor}]\n"
    )


@app.command()
def cvm_baixar(
    anos: int = typer.Option(6, help="Profundidade, em anos."),
) -> None:
    """Baixa os balanços oficiais da CVM (ITR + DFP), com a DATA DE PUBLICAÇÃO.

    É a fundação de tudo: sem balanço não há tese verificável nem preço teto. E o `DT_RECEB`
    é o que torna a análise honesta — sem ele, o sistema "saberia" em 30/09 um resultado que
    só foi publicado em 12/11.
    """
    from app.ingest import cvm

    ano_fim = datetime.now(UTC).year
    lista = list(range(ano_fim - anos + 1, ano_fim + 1))

    console.print(f"[bold]CVM[/bold] · ITR + DFP · {lista[0]}–{lista[-1]}\n")

    mapa = cvm.mapa_tickers()
    console.print(f"  mapa oficial CNPJ → ticker: [bold]{len(mapa)}[/bold] papéis\n")

    painel = cvm.load(lista)
    if painel.empty:
        console.print("[red]nada baixado[/red]")
        raise typer.Exit(1)

    com_data = painel["dt_receb"].notna().mean() * 100
    console.print(
        f"\n[bold green]{len(painel):,}[/bold green] linhas · "
        f"{painel['cnpj'].nunique()} empresas · "
        f"{com_data:.0f}% com data de publicação"
    )
    for doc, n in painel["doc"].value_counts().items():
        console.print(f"  [dim]{doc}: {n:,}[/dim]")


@app.command()
def fundamentos(
    tickers: str = typer.Argument("PETR4,ITUB4,TAEE3,SAPR4,CMIG4,BBDC4,KLBN4"),
) -> None:
    """Mostra os fundamentos calculados a partir do balanço da CVM.

    A validação que importa: se esses números não baterem com a realidade, tudo o que vem
    em cima deles é lixo.
    """
    from app.engine import fundamentos as fd
    from app.ingest import cvm

    ano_fim = datetime.now(UTC).year
    painel = cvm.load(list(range(ano_fim - 5, ano_fim + 1)))
    mapa = cvm.mapa_tickers()

    t = Table("Papel", "Base", "Publicado", "LPA", "VPA", "DPA", "ROE", "Payout",
              "DívLíq/EBIT", "Margem")
    for tk in [x.strip().upper() for x in tickers.split(",")]:
        linha = mapa[mapa["ticker"] == tk]
        if linha.empty:
            t.add_row(tk, "[red]sem CNPJ[/red]", "", "", "", "", "", "", "", "")
            continue

        cnpj = linha["cnpj"].iloc[0]
        f = fd.calcular(painel[painel["cnpj"] == cnpj], tk, linha["empresa"].iloc[0])
        if f is None:
            t.add_row(tk, "[red]sem balanço[/red]", "", "", "", "", "", "", "", "")
            continue

        def n(v, fmt="{:.2f}"):
            return fmt.format(v) if v is not None else "—"

        pay = f.payout
        cor_pay = "red" if (pay and pay > 1.0) else "white"

        t.add_row(
            tk,
            f"{f.data_base:%Y-%m}",
            f"{f.data_publicacao:%Y-%m-%d}",
            n(f.lpa), n(f.vpa), n(f.dpa),
            n(f.roe, "{:.1%}"),
            f"[{cor_pay}]{n(pay, '{:.0%}')}[/{cor_pay}]",
            n(f.divida_ebit, "{:.1f}x"),
            n(f.margem, "{:.1%}"),
        )
    console.print(t)
    console.print(
        "[dim]DPA vem do FLUXO DE CAIXA auditado (dividendos + JCP pagos ÷ ações), "
        "não do Yahoo —\nque reporta 1 pagamento de R$ 0,1125 para a SAPR4 e payout de "
        "425% para a KLBN4.[/dim]"
    )


@app.command()
def valor(
    market: Market = typer.Option(Market.B3, help="B3 ou US."),
    top: int = typer.Option(15, help="Quantos exibir."),
) -> None:
    """Triagem fundamentalista: o que está barato PARA CARREGAR (SPEC §12).

    Pergunta diferente do resto do motor. A reversão pergunta "vai repicar em 10 pregões?";
    esta é sobre anos. Não é conselho de compra — é uma lista do que merece ler o balanço.
    """
    from app.engine import value
    from app.ingest import fundamentals

    ativos = watchlist(market)
    console.print(f"[bold]Triagem fundamentalista[/bold] · {market.value} · {len(ativos)} papéis")
    console.print("[dim]buscando fundamentos…[/dim]\n")

    avaliacoes = []
    for a in ativos:
        f = fundamentals.fetch(a)
        precos = store.read(a, Timeframe.D1)
        hist = precos["close"] if not precos.empty else None
        if (av := value.avaliar(f, hist)) is not None:
            avaliacoes.append(av)

    if not avaliacoes:
        console.print("[yellow]nenhum papel com LPA e VPA disponíveis[/yellow]")
        raise typer.Exit(1)

    avaliacoes.sort(key=lambda x: -x.score)

    t = Table("Papel", "Preço", "Graham", "Margem", "P/L", "P/VP", "vs. própria história",
              "Score")
    for av in avaliacoes[:top]:
        cor = "green" if av.score >= 60 else ("yellow" if av.score >= 35 else "dim")
        t.add_row(
            av.ticker.removesuffix(".SA"),
            f"{av.preco:.2f}",
            f"{av.graham:.2f}" if av.graham else "—",
            f"[{cor}]{av.margem_graham:+.0f}%[/{cor}]" if av.margem_graham else "—",
            f"{av.pl:.1f}" if av.pl else "—",
            f"{av.pvp:.2f}" if av.pvp else "—",
            f"{av.desconto_vs_historia:+.0f}%" if av.desconto_vs_historia else "—",
            f"[{cor}]{av.score}[/{cor}]",
        )
    console.print(t)
    console.print(
        f"[dim]{len(avaliacoes)} papéis avaliados · "
        "margem = desconto contra o valor intrínseco de Graham[/dim]"
    )

    com_alerta = [av for av in avaliacoes[:top] if av.alertas]
    if com_alerta:
        console.print("\n[yellow]Ressalvas contábeis:[/yellow]")
        for av in com_alerta:
            for x in av.alertas:
                console.print(f"  [dim]{av.ticker.removesuffix('.SA')}:[/dim] {x}")


@app.command()
def universo_b3(
    top: int = typer.Option(120, help="Quantos papéis compõem o universo em cada mês."),
    anos: int = typer.Option(20),
) -> None:
    """Reconstrói o universo POINT-IN-TIME da B3, com os papéis que morreram.

    Sem isto, o backtest só vê quem sobreviveu — e as empresas que quebraram, que são
    justamente as que dariam prejuízo, sumiram da amostra. O resultado é inflado.
    """
    from app.core import b3_universe

    console.print(f"[bold]Universo B3[/bold] · top {top} por liquidez, revisto todo mês\n")
    painel, comp = b3_universe.build(top_n=top, anos=anos)
    b3_universe.save(painel, comp)

    vivos = {a.ticker.removesuffix(".SA") for a in watchlist(Market.B3)}
    membros = set(comp["ticker"])
    mortos = sorted(membros - vivos)

    console.print(
        f"  {len(membros)} papéis já pertenceram ao universo · "
        f"{len(painel):,} velas · {comp['data'].nunique()} rebalanceamentos"
    )
    console.print(
        f"  [bold yellow]{len(mortos)}[/bold yellow] deles NÃO estão na watchlist de hoje "
        f"[dim](deslistados, incorporados ou definhados — é a amostra que faltava)[/dim]"
    )
    console.print(f"  [dim]{', '.join(mortos[:40])}{' …' if len(mortos) > 40 else ''}[/dim]")

    # A prova de que o universo é mesmo point-in-time: a composição MUDA ao longo do tempo.
    primeira, ultima = comp["data"].min(), comp["data"].max()
    a = set(b3_universe.membros_em(comp, primeira))
    b = set(b3_universe.membros_em(comp, ultima))
    console.print(
        f"\n  [dim]composição em {primeira:%Y-%m}: {len(a)} papéis · "
        f"em {ultima:%Y-%m}: {len(b)} · em comum: {len(a & b)} "
        f"→ {len(a - b)} saíram, {len(b - a)} entraram[/dim]"
    )


@app.command()
def preview(
    ticker: str = typer.Argument(..., help="Ex: BTCUSDT"),
    timeframe: str = typer.Argument("1d"),
) -> None:
    """Roda o motor sobre o histórico e mostra o FUNIL de filtros.

    Não é o backtest (Fase 2): não há walk-forward nem out-of-sample. Serve para ver onde
    os sinais morrem — que é a informação que decide o que calibrar.
    """
    from app.core.config import load_params
    from app.engine import indicators, regime, signals
    from app.engine.regime import MarketRegime

    asset = next((a for a in watchlist() if a.ticker == ticker), None)
    if asset is None:
        raise typer.BadParameter(f"{ticker} não está na watchlist")

    tf = Timeframe(timeframe)
    p = load_params(asset.market, tf)  # perfil do ativo, não parâmetro global
    df = store.read(asset, tf)
    if df.empty:
        raise typer.BadParameter("série vazia — rode `dands backfill`")

    f = indicators.compute(df, p)
    f["market_regime"] = regime.classify(f, p)
    pronto = f.dropna(subset=["market_regime", "deviation_from_mean", "volume_z_score", "atr"])

    lateral = pronto["market_regime"] == MarketRegime.LATERAL.value
    banda = pronto["deviation_from_mean"].abs() >= p.bandas.n_sigma_entrada
    vol = pronto["volume_z_score"] >= p.volume.z_minimo
    sinais = signals.generate(pronto, p, asset.market)

    console.print(f"\n[bold]{asset.ticker}[/bold] {tf.value} · {len(pronto)} velas avaliáveis")

    t = Table("Filtro", "Velas", "% do total")
    for nome, mask in [
        ("tocou a banda (±2σ)", banda),
        ("  ...e volume confirmou", banda & vol),
        ("  ...e regime LATERAL", banda & vol & lateral),
    ]:
        n = int(mask.sum())
        t.add_row(nome, str(n), f"{100 * n / len(pronto):.2f}%")
    t.add_row("  ...e passou no R:R ≥ 2", f"[bold]{len(sinais)}[/bold]",
              f"[bold]{100 * len(sinais) / len(pronto):.3f}%[/bold]")
    console.print(t)

    r = Table("Regime", "Velas", "%")
    for nome, n in pronto["market_regime"].value_counts().items():
        r.add_row(str(nome), str(n), f"{100 * n / len(pronto):.1f}%")
    console.print(r)

    if len(sinais):
        console.print(
            f"\n[dim]score: mediana {sinais['calculated_score'].median():.0f} · "
            f"R:R mediano {sinais['rr'].median():.2f} · "
            f"compras {(sinais['alert_type'] == 'BUY').sum()} / "
            f"vendas {(sinais['alert_type'] == 'SELL').sum()}[/dim]"
        )


@db_app.command("init")
def db_init() -> None:
    """Aplica infra/schema.sql. Idempotente."""

    async def _run() -> None:
        from app.core import db

        await db.init_schema()
        conn = await db.connect()
        try:
            tabelas = await conn.fetch(
                "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY 1"
            )
        finally:
            await conn.close()
        console.print("[green]Schema aplicado.[/green] Tabelas: " +
                      ", ".join(t["tablename"] for t in tabelas))

    asyncio.run(_run())


@db_app.command("load")
def db_load(market: Market | None = typer.Option(None)) -> None:
    """Carrega o Parquet no Postgres. Idempotente (upsert por vela)."""

    async def _run() -> None:
        from app.core import db

        conn = await db.connect()
        try:
            ids = await db.sync_assets(conn)
            console.print(f"[dim]{len(ids)} ativos sincronizados.[/dim]\n")

            total = 0
            for asset in watchlist(market):
                for tf in asset.timeframes:
                    n = await db.load_series(conn, asset, tf, ids[asset.ticker])
                    total += n
                    console.print(f"  [green]→[/green] {asset.ticker:<10} {tf.value:<4} "
                                  f"[dim]{n} velas[/dim]")

            n_db = await conn.fetchval("SELECT COUNT(*) FROM asset_prices")
        finally:
            await conn.close()

        console.print(f"\n[bold green]{total}[/bold green] velas enviadas · "
                      f"[bold]{n_db}[/bold] no banco.")

    asyncio.run(_run())


@db_app.command("account")
def db_account(
    currency: str = typer.Argument(..., help="BRL ou USD (USDT conta como USD)."),
    saldo: float = typer.Option(..., "--saldo", help="Saldo inicial da banca."),
    risco: float = typer.Option(
        1.0, "--risco", help="%% da banca arriscado por operação (sizing, SPEC §8.2)."
    ),
) -> None:
    """Cria ou atualiza uma banca. Uma por moeda (SPEC §8.1)."""
    currency = currency.upper()
    if currency not in ("BRL", "USD"):
        raise typer.BadParameter("moeda deve ser BRL ou USD")

    async def _run() -> None:
        from decimal import Decimal

        from app.core import db

        conn = await db.connect()
        try:
            await db.upsert_account(
                conn, currency, Decimal(str(saldo)), Decimal(str(risco))
            )
            contas = await conn.fetch(
                "SELECT currency, initial_balance, cash_balance, risk_per_trade_pct "
                "FROM accounts ORDER BY currency"
            )
        finally:
            await conn.close()

        for c in contas:
            console.print(
                f"  [bold]{c['currency']}[/bold]  inicial {c['initial_balance']:,.2f} · "
                f"caixa {c['cash_balance']:,.2f} · risco {c['risk_per_trade_pct']}%/trade"
            )

    asyncio.run(_run())


if __name__ == "__main__":
    app()
