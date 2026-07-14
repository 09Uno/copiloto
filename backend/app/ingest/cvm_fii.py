"""CVM — informe mensal de FII, POINT-IN-TIME.

O FII tem métricas próprias, e a mais importante **não é o dividendo: é o P/VP**. Um FII é um
fundo — ele tem patrimônio contábil por cota, publicado todo mês. Comprar a 0,87× o patrimônio
é diferente de comprar a 1,25×, e essa diferença não existe em ação com a mesma clareza.

O que a CVM entrega (e o `Data_Entrega` mantém tudo point-in-time):
  · **Valor_Patrimonial_Cotas** — o VP da cota, base do P/VP
  · **Patrimonio_Liquido**, **Cotas_Emitidas**
  · **Total_Passivo** — alavancagem
  · composição do ativo (imóveis × CRI) — de onde se **deduz** se é TIJOLO ou PAPEL
  · **Total_Numero_Cotistas** — pulverização

**O que a CVM NÃO entrega: vacância.** Ela vive no relatório gerencial do fundo (FNET), que não
é dado estruturado. O sistema vai **dizer que não sabe**, em vez de inventar.

E o `Percentual_Dividend_Yield_Mes` da CVM **é lixo** — vem 0% para a GARE11, que paga ~0,9% ao
mês. O rendimento vem do yfinance, que para FII é confiável (distribuição mensal simples, sem a
complicação do JCP que ele erra nas ações).
"""

from __future__ import annotations

import io
import zipfile

import httpx
import pandas as pd

from app.core.config import DATA_DIR

URL = "https://dados.cvm.gov.br/dados/FII/DOC/INF_MENSAL/DADOS/inf_mensal_fii_{ano}.zip"
CACHE = DATA_DIR / "cvm_fii"
CACHE_VERSAO = "v1"

# O ISIN brasileiro de FII costuma embutir o prefixo do papel: BRGARECTF001 → GARE11.
# **Mas nem sempre:** o BTHF11 é BR0EI9CTF007 (prefixo "0EI9"). As exceções ficam aqui,
# explícitas — e o sistema AVISA quais FIIs não conseguiu mapear, em vez de fingir.
ISIN_EXCECOES: dict[str, str] = {
    "BR0EI9CTF007": "BTHF11",
}


def _baixar(ano: int) -> zipfile.ZipFile | None:
    try:
        r = httpx.get(URL.format(ano=ano), timeout=300.0, follow_redirects=True)
        r.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        print(f"  ! FII {ano}: {exc}")
        return None
    return zipfile.ZipFile(io.BytesIO(r.content))


def _num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce")


def fetch_ano(ano: int, force: bool = False) -> pd.DataFrame:
    """Um ano de informe mensal, já cruzado (geral + complemento + ativo/passivo)."""
    CACHE.mkdir(parents=True, exist_ok=True)
    p = CACHE / f"{ano}_{CACHE_VERSAO}.parquet"
    if p.exists() and not force:
        return pd.read_parquet(p)

    z = _baixar(ano)
    if z is None:
        return pd.DataFrame()

    def csv(nome: str) -> pd.DataFrame:
        alvo = f"inf_mensal_fii_{nome}_{ano}.csv"
        if alvo not in z.namelist():
            return pd.DataFrame()
        return pd.read_csv(z.open(alvo), sep=";", encoding="latin-1", dtype=str)

    geral, comp, ap = csv("geral"), csv("complemento"), csv("ativo_passivo")
    if geral.empty or comp.empty:
        return pd.DataFrame()

    chave = ["CNPJ_Fundo_Classe", "Data_Referencia"]

    g = geral.assign(
        cnpj=geral["CNPJ_Fundo_Classe"],
        dt_refer=pd.to_datetime(geral["Data_Referencia"], errors="coerce"),
        # Data_Entrega = quando o informe virou público. É o point-in-time do FII.
        dt_entrega=pd.to_datetime(geral["Data_Entrega"], errors="coerce"),
        nome=geral["Nome_Fundo_Classe"],
        isin=geral["Codigo_ISIN"],
        ticker=geral["Codigo_ISIN"].map(_ticker_do_isin),
    )[["cnpj", "dt_refer", "dt_entrega", "nome", "isin", "ticker"]].drop_duplicates(
        subset=["cnpj", "dt_refer"], keep="last"
    )

    c = comp.assign(
        cnpj=comp["CNPJ_Fundo_Classe"],
        dt_refer=pd.to_datetime(comp["Data_Referencia"], errors="coerce"),
        vp_cota=_num(comp["Valor_Patrimonial_Cotas"]),
        patrimonio=_num(comp["Patrimonio_Liquido"]),
        cotas=_num(comp["Cotas_Emitidas"]),
        cotistas=_num(comp["Total_Numero_Cotistas"]),
        ativo_total=_num(comp["Valor_Ativo"]),
    )[["cnpj", "dt_refer", "vp_cota", "patrimonio", "cotas", "cotistas",
       "ativo_total"]].drop_duplicates(subset=["cnpj", "dt_refer"], keep="last")

    out = g.merge(c, on=["cnpj", "dt_refer"], how="inner")

    if not ap.empty:
        # A composição do ativo diz o que o fundo REALMENTE é — muito melhor que o campo
        # "Segmento_Atuacao", que vem "Multicategoria" para todo mundo.
        # **A SPE conta como imóvel.** Muitos FIIs detêm os prédios através de sociedades de
        # propósito específico — o imóvel aparece como "Ações/Cotas de Sociedades com
        # Atividades de FII", não como imóvel direto. Sem incluí-las, a GARE11 (logística
        # pura) saía com "17% em imóvel" e o sistema a classificaria errado.
        imoveis = [
            "Imoveis_Renda_Acabados", "Imoveis_Renda_Construcao", "Terrenos",
            "Imoveis_Venda_Acabados", "Imoveis_Venda_Construcao", "Outros_Direitos_Reais",
            "Acoes_Sociedades_Atividades_FII", "Cotas_Sociedades_Atividades_FII",
        ]
        papel = ["CRI", "CRI_CRA", "LCI", "LCI_LCA", "LIG", "Letras_Hipotecarias"]

        a = ap.assign(
            cnpj=ap["CNPJ_Fundo_Classe"],
            dt_refer=pd.to_datetime(ap["Data_Referencia"], errors="coerce"),
            valor_imoveis=sum(_num(ap[c]).fillna(0) for c in imoveis if c in ap.columns),
            valor_papel=sum(_num(ap[c]).fillna(0) for c in papel if c in ap.columns),
            valor_cotas_fii=_num(ap["FII"]).fillna(0) if "FII" in ap.columns else 0.0,
            passivo=_num(ap["Total_Passivo"]),
        )[["cnpj", "dt_refer", "valor_imoveis", "valor_papel", "valor_cotas_fii",
           "passivo"]].drop_duplicates(subset=["cnpj", "dt_refer"], keep="last")

        out = out.merge(a, on=["cnpj", "dt_refer"], how="left")

    out = out.dropna(subset=["dt_refer"]).reset_index(drop=True)
    out.to_parquet(p, index=False, compression="zstd")
    return out


def _ticker_do_isin(isin: str | float) -> str | None:
    if not isinstance(isin, str) or len(isin) < 6:
        return None
    if isin in ISIN_EXCECOES:
        return ISIN_EXCECOES[isin]
    prefixo = isin[2:6]
    return f"{prefixo}11" if prefixo.isalpha() else None


def load(anos: list[int]) -> pd.DataFrame:
    atual = pd.Timestamp.now().year
    partes = [fetch_ano(a, force=(a == atual)) for a in anos]
    partes = [p for p in partes if not p.empty]
    return pd.concat(partes, ignore_index=True) if partes else pd.DataFrame()
