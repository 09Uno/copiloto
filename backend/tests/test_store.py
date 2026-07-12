"""As invariantes do store são premissa de todo o resto: se a série tiver duplicata,
estiver fora de ordem ou com fuso errado, o backtest mede a coisa errada e ninguém percebe.
"""

from __future__ import annotations

import pandas as pd
import pytest

from app.core.config import Asset, Market, Timeframe
from app.ingest import store

ASSET = Asset(ticker="TESTE", market=Market.CRYPTO, name="Fixture",
              timeframes=(Timeframe.D1,))


@pytest.fixture(autouse=True)
def _tmp_data(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)


def _velas(inicio: str, n: int) -> pd.DataFrame:
    ts = pd.date_range(inicio, periods=n, freq="1D", tz="UTC")
    return pd.DataFrame(
        {
            "timestamp": ts,
            "open": range(n),
            "high": range(n),
            "low": range(n),
            "close": range(n),
            "volume": [100.0] * n,
        }
    )


def test_reingerir_o_mesmo_periodo_e_no_op():
    assert store.upsert(ASSET, Timeframe.D1, _velas("2024-01-01", 5)) == 5
    assert store.upsert(ASSET, Timeframe.D1, _velas("2024-01-01", 5)) == 0
    assert len(store.read(ASSET, Timeframe.D1)) == 5


def test_lote_sobreposto_conta_so_as_velas_novas():
    store.upsert(ASSET, Timeframe.D1, _velas("2024-01-01", 5))
    # 2024-01-04..08: 2 sobrepõem, 3 são novas
    assert store.upsert(ASSET, Timeframe.D1, _velas("2024-01-04", 5)) == 3
    assert len(store.read(ASSET, Timeframe.D1)) == 8


def test_revisao_da_fonte_sobrescreve_a_vela_antiga():
    store.upsert(ASSET, Timeframe.D1, _velas("2024-01-01", 3))
    revisado = _velas("2024-01-01", 3)
    revisado.loc[1, "close"] = 999.0

    store.upsert(ASSET, Timeframe.D1, revisado)
    df = store.read(ASSET, Timeframe.D1)

    assert len(df) == 3
    assert df.loc[1, "close"] == 999.0


def test_serie_sai_ordenada_e_sem_duplicata_mesmo_com_lote_bagunçado():
    bagunçado = pd.concat([_velas("2024-01-03", 2), _velas("2024-01-01", 3)])
    store.upsert(ASSET, Timeframe.D1, bagunçado)
    ts = store.read(ASSET, Timeframe.D1)["timestamp"]

    assert ts.is_monotonic_increasing
    assert not ts.duplicated().any()


def test_timestamp_ingenuo_e_promovido_a_utc():
    df = _velas("2024-01-01", 2)
    df["timestamp"] = df["timestamp"].dt.tz_localize(None)  # perde o fuso

    store.upsert(ASSET, Timeframe.D1, df)

    assert str(store.read(ASSET, Timeframe.D1)["timestamp"].dt.tz) == "UTC"


def test_vela_sem_preco_e_descartada_mas_volume_zero_e_legitimo():
    df = _velas("2024-01-01", 3)
    df.loc[1, "close"] = None   # preço faltando → lixo
    df.loc[2, "volume"] = None  # pregão parado → válido, vira 0

    store.upsert(ASSET, Timeframe.D1, df)
    out = store.read(ASSET, Timeframe.D1)

    assert len(out) == 2
    assert out["volume"].iloc[-1] == 0.0


def test_serie_inexistente_le_como_vazia_e_nao_explode():
    assert store.read(ASSET, Timeframe.D1).empty
    assert store.last_timestamp(ASSET, Timeframe.D1) is None
