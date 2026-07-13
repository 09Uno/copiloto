"""COTAHIST — série histórica oficial da B3 (EOD).

Por que trocar o Yahoo por isto:

1. **Mata o viés de sobrevivência.** O COTAHIST contém TODO papel que negociou no ano, inclusive
   os que morreram depois. O universo montado a partir do Yahoo é a lista dos líquidos de HOJE —
   um backtest sobre ela só vê quem sobreviveu, e por isso **superestima o retorno**. É a
   limitação mais séria que o projeto tinha.

2. **É oficial.** Sem "possibly delisted" para a Embraer, sem SLA inexistente, sem quebrar
   quando o Yahoo muda de humor.

3. **Vai fundo.** Décadas, de graça, direto da bolsa.

Layout: registro de largura fixa, 245 bytes, especificado pela própria B3.
Preços vêm em centavos (2 decimais implícitos) — daí a divisão por 100.
"""

from __future__ import annotations

import io
import zipfile

import httpx
import pandas as pd

from app.core.config import DATA_DIR

URL = "https://bvmf.bmfbovespa.com.br/InstDados/SerHist/COTAHIST_A{ano}.ZIP"
CACHE = DATA_DIR / "cotahist"

# Posições (0-indexadas, semiabertas) conforme o layout oficial da B3.
COLSPECS = [
    (0, 2),      # TIPREG — '01' = cotação
    (2, 10),     # DATA   — AAAAMMDD
    (10, 12),    # CODBDI — '02' = lote padrão
    (12, 24),    # CODNEG — o ticker
    (24, 27),    # TPMERC — '010' = mercado à vista
    (56, 69),    # PREABE — abertura
    (69, 82),    # PREMAX — máxima
    (82, 95),    # PREMIN — mínima
    (108, 121),  # PREULT — fechamento
    (152, 170),  # QUATOT — quantidade negociada
    (170, 188),  # VOLTOT — volume FINANCEIRO (é o que o SPEC §2.3 quer)
]
NAMES = [
    "tipreg", "data", "codbdi", "codneg", "tpmerc",
    "open", "high", "low", "close", "quantidade", "volume",
]

CODBDI_LOTE_PADRAO = "02"  # exclui fracionário, leilão, direitos, etc.
TPMERC_VISTA = "010"       # só mercado à vista: nada de termo, opção ou futuro


def _parse(raw: bytes) -> pd.DataFrame:
    df = pd.read_fwf(
        io.BytesIO(raw),
        colspecs=COLSPECS,
        names=NAMES,
        dtype=str,
        encoding="latin-1",
        header=None,
    )

    # A primeira e a última linha são header/trailer do arquivo (TIPREG 00 e 99).
    df = df[df["tipreg"] == "01"]
    df = df[(df["codbdi"] == CODBDI_LOTE_PADRAO) & (df["tpmerc"] == TPMERC_VISTA)]
    if df.empty:
        return df

    out = pd.DataFrame(
        {
            "ticker": df["codneg"].str.strip(),
            # 00:00 UTC do pregão. O COTAHIST é EOD: a hora não existe, só a data.
            "timestamp": pd.to_datetime(df["data"], format="%Y%m%d", utc=True),
        }
    )
    for c in ("open", "high", "low", "close"):
        out[c] = pd.to_numeric(df[c], errors="coerce") / 100.0  # centavos → reais
    out["volume"] = pd.to_numeric(df["volume"], errors="coerce") / 100.0  # financeiro, em R$

    return out.dropna(subset=["open", "high", "low", "close"])


def fetch_ano(ano: int, force: bool = False) -> pd.DataFrame:
    """Baixa e parseia um ano. O resultado fica em cache — o ZIP não muda nunca."""
    CACHE.mkdir(parents=True, exist_ok=True)
    cache = CACHE / f"{ano}.parquet"

    if cache.exists() and not force:
        return pd.read_parquet(cache)

    r = httpx.get(URL.format(ano=ano), timeout=180.0, follow_redirects=True)
    r.raise_for_status()

    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        raw = z.read(z.namelist()[0])

    df = _parse(raw)
    df.to_parquet(cache, index=False, compression="zstd")
    return df


def load(anos: list[int]) -> pd.DataFrame:
    """Vários anos concatenados. O ano corrente é sempre rebaixado (ainda está crescendo)."""
    from datetime import UTC, datetime

    ano_atual = datetime.now(UTC).year
    partes = []
    for a in anos:
        try:
            partes.append(fetch_ano(a, force=(a == ano_atual)))
        except Exception as exc:  # noqa: BLE001 — ano faltante não derruba o lote
            print(f"  ! COTAHIST {a}: {exc}")
    return pd.concat(partes, ignore_index=True) if partes else pd.DataFrame()
