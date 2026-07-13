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

import typer
from rich.console import Console
from rich.table import Table

from app.core.config import Asset, Market, Timeframe, watchlist
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
            if not full:
                ultimo = store.last_timestamp(asset, tf)
                if ultimo is not None:
                    # Retoma da última vela (e não da seguinte): reescrevê-la é barato
                    # e cobre o caso de ela ter sido gravada ainda em formação.
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
