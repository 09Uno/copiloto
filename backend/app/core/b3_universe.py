"""Universo POINT-IN-TIME da B3 — o conserto do viés de sobrevivência.

O problema: montar o universo com os líquidos de HOJE e rodar o backtest sobre 20 anos é
olhar só para quem sobreviveu. As empresas que quebraram, foram deslistadas ou definharam
sumiram da amostra — e elas são justamente as que dariam prejuízo. O backtest então
**superestima o retorno**, e não por pouco. É o viés mais clássico e mais caro do backtest de
ações, e o mais fácil de cometer sem perceber.

O conserto: em cada data, o universo é quem era líquido **naquela data** — usando só
informação disponível até ali. A Americanas entra em 2019 e sai em 2023. A IRB entra e
despenca. O backtest passa a viver o que você teria vivido.

O COTAHIST torna isso possível porque contém TODO papel que negociou, inclusive os mortos.
O Yahoo, não: ele só conhece quem está vivo.
"""

from __future__ import annotations

import pandas as pd

from app.core.config import DATA_DIR
from app.ingest import cotahist

CACHE = DATA_DIR / "universe"

JANELA_LIQUIDEZ = 60   # pregões — liquidez é média de médio prazo, não de um dia
MIN_PREGOES = 200      # papel novo demais não tem história para as janelas do motor
REBALANCE = "ME"       # revisita a composição no fim de cada mês


def build(top_n: int = 120, anos: int = 20) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Devolve (painel, composicao).

    painel     — OHLCV de todo papel que já pertenceu ao universo (inclusive os mortos).
    composicao — (data, ticker): quem estava no universo em cada rebalanceamento.

    A liquidez é medida por VOLUME FINANCEIRO (R$), que é invariante a desdobramento.
    """
    from datetime import UTC, datetime

    ano_fim = datetime.now(UTC).year
    bruto = cotahist.load(list(range(ano_fim - anos + 1, ano_fim + 1)))
    if bruto.empty:
        raise RuntimeError("COTAHIST vazio")

    acoes = bruto[cotahist.eh_acao(bruto["especi"])].copy()

    # Liquidez móvel por papel. `rolling` só olha para trás — é o que mantém o universo
    # point-in-time. Rankear por liquidez do período INTEIRO seria lookahead puro: a
    # Americanas teria ficado de fora de 2019 porque quebrou em 2023.
    acoes = acoes.sort_values(["ticker", "timestamp"])
    acoes["liquidez"] = (
        acoes.groupby("ticker")["volume"]
        .rolling(JANELA_LIQUIDEZ, min_periods=JANELA_LIQUIDEZ)
        .median()
        .reset_index(level=0, drop=True)
    )
    acoes["n_pregoes"] = acoes.groupby("ticker").cumcount() + 1

    elegivel = acoes[acoes["liquidez"].notna() & (acoes["n_pregoes"] >= MIN_PREGOES)]

    # Composição em cada fim de mês: os top_n mais líquidos naquele instante.
    datas = (
        elegivel.set_index("timestamp").resample(REBALANCE).last().dropna(how="all").index
    )
    partes = []
    for data in datas:
        do_dia = elegivel[elegivel["timestamp"] == _ultimo_pregao(elegivel, data)]
        if do_dia.empty:
            continue
        top = do_dia.nlargest(top_n, "liquidez")[["ticker", "liquidez"]].copy()
        top["data"] = data
        partes.append(top)

    composicao = pd.concat(partes, ignore_index=True) if partes else pd.DataFrame()
    membros = set(composicao["ticker"]) if not composicao.empty else set()
    painel = acoes[acoes["ticker"].isin(membros)].drop(columns=["liquidez", "n_pregoes"])

    return painel.reset_index(drop=True), composicao


def _ultimo_pregao(df: pd.DataFrame, ate: pd.Timestamp) -> pd.Timestamp:
    anteriores = df.loc[df["timestamp"] <= ate, "timestamp"]
    return anteriores.max() if len(anteriores) else ate


def save(painel: pd.DataFrame, composicao: pd.DataFrame) -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    painel.to_parquet(CACHE / "b3_painel.parquet", index=False, compression="zstd")
    composicao.to_parquet(CACHE / "b3_composicao.parquet", index=False, compression="zstd")


def load() -> tuple[pd.DataFrame, pd.DataFrame]:
    return (
        pd.read_parquet(CACHE / "b3_painel.parquet"),
        pd.read_parquet(CACHE / "b3_composicao.parquet"),
    )


def membros_em(composicao: pd.DataFrame, data: pd.Timestamp) -> list[str]:
    """Quem estava no universo NAQUELA data. É esta função que o backtest deve chamar —
    nunca a lista de hoje."""
    passadas = composicao.loc[composicao["data"] <= data, "data"]
    if passadas.empty:
        return []
    ultima = passadas.max()
    return composicao.loc[composicao["data"] == ultima, "ticker"].tolist()
