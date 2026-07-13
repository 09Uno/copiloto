"""Features do motor (SPEC §2). Módulo PURO: recebe DataFrame, devolve DataFrame.

Sem banco, sem rede, sem relógio. É o que permite o backtest (Fase 2) e a produção (Fase 3)
rodarem exatamente o mesmo código — se fossem duas implementações, divergiriam e o backtest
viraria ficção.

SEM LOOKAHEAD. Toda janela termina na vela corrente (que já fechou) e olha para trás.
Nenhuma estatística é ajustada sobre o histórico inteiro: fazer isso é vazamento — o
normalizador enxergaria o futuro (é o motivo de o `state_vector` do SPEC §9 ser
adimensional por construção).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.core.config import Params


def _rolling_ols_log(close: pd.Series, janela: int) -> tuple[pd.Series, pd.Series]:
    """Regressão de ln(preço) contra o tempo, em janela móvel → (slope, r2).

    Sobre LOG-preço de propósito (SPEC §2.1): o slope vira retorno logarítmico por período,
    comparável entre BTC (dezenas de milhares) e PETR4 (dezenas) e estável ao longo do tempo.
    Como essa é uma feature de ENTRADA do modelo, alimentar o ML com preço bruto seria
    entregar uma variável de escala incomparável.

    Forma fechada em vez de `rolling().apply(polyfit)`: o x é sempre [0..n-1], então as somas
    de x são constantes e as de y saem de somas móveis. O grid search da Fase 2 chama isto
    milhares de vezes — polyfit levaria minutos onde isto leva milissegundos.
    """
    n = janela
    y = np.log(close.to_numpy(dtype=float))

    x = np.arange(n, dtype=float)
    sx = x.sum()
    sxx = (x * x).sum()
    den_x = n * sxx - sx * sx  # variância de x (constante)

    sy = pd.Series(y, index=close.index).rolling(n).sum().to_numpy()
    syy = pd.Series(y * y, index=close.index).rolling(n).sum().to_numpy()

    # Σ(x·y) da janela = correlação de y com o kernel [0..n-1].
    sxy = np.full(len(y), np.nan)
    if len(y) >= n:
        sxy[n - 1 :] = np.correlate(y, x, mode="valid")

    num = n * sxy - sx * sy
    slope = num / den_x

    den_y = n * syy - sy * sy

    # Guarda RELATIVO, não `den_y > 0`. Numa série (quase) plana, den_y é a diferença de dois
    # números grandes e quase iguais: o resultado é ruído de float. Um `> 0` ingênuo deixaria
    # passar um R² espúrio — potencialmente ALTO — e o motor classificaria TENDENCIA onde não
    # há tendência nenhuma, travando a operação para sempre.
    with np.errstate(divide="ignore", invalid="ignore"):
        eps = 1e-12 * np.maximum(np.abs(n * syy), 1.0)
        r2 = np.where(den_y > eps, (num * num) / (den_x * den_y), 0.0)

    r2 = np.clip(r2, 0.0, 1.0)
    r2[np.isnan(slope)] = np.nan

    return (
        pd.Series(slope, index=close.index, name="regression_slope"),
        pd.Series(r2, index=close.index, name="regression_r2"),
    )


def _atr(df: pd.DataFrame, janela: int) -> pd.Series:
    """ATR de Wilder. O True Range usa o fechamento ANTERIOR — daí o shift(1)."""
    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    # Suavização de Wilder = EMA com alpha = 1/n (não a EMA padrão do pandas).
    return tr.ewm(alpha=1 / janela, adjust=False, min_periods=janela).mean()


def compute(df: pd.DataFrame, p: Params) -> pd.DataFrame:
    """Anexa as features de SPEC §2 ao OHLCV. As primeiras `p.min_velas` linhas saem NaN."""
    out = df.copy()

    # --- Regressão sobre log-preço → tendência e sua NITIDEZ (§2.1)
    out["regression_slope"], out["regression_r2"] = _rolling_ols_log(
        out["close"], p.regressao.janela
    )

    # --- Bandas de desvio padrão (§2.2)
    jm = p.bandas.janela_media
    out["mu"] = out["close"].rolling(jm).mean()
    sigma = out["close"].rolling(jm).std(ddof=0)
    out["sigma"] = sigma
    # sigma == 0 (preço travado) → não há distorção a medir, e não uma divisão por zero.
    out["deviation_from_mean"] = np.where(
        sigma > 0, (out["close"] - out["mu"]) / sigma, 0.0
    )
    out.loc[sigma.isna(), "deviation_from_mean"] = np.nan

    # --- Z-score sobre LOG-volume (§2.3)
    # log1p e não log: pregão parado tem volume 0, e ln(0) = -inf contaminaria a janela inteira.
    lv = np.log1p(out["volume"])
    jz = p.volume.janela_zscore
    mu_v = lv.rolling(jz).mean()
    sd_v = lv.rolling(jz).std(ddof=0)
    out["volume_z_score"] = np.where(sd_v > 0, (lv - mu_v) / sd_v, 0.0)
    out.loc[sd_v.isna(), "volume_z_score"] = np.nan

    # --- ATR e sua fração do preço (§2.4). atr_pct é adimensional → entra no state_vector.
    out["atr"] = _atr(out, p.risco.atr_janela)
    out["atr_pct"] = out["atr"] / out["close"]

    # Mediana móvel do ATR% — referência do choque de volatilidade (regime NERVOSO).
    out["atr_pct_mediana"] = out["atr_pct"].rolling(p.regime.nervoso_atr_janela).median()

    return out


FEATURES = [
    "regression_slope",
    "regression_r2",
    "deviation_from_mean",
    "volume_z_score",
    "atr_pct",
]
