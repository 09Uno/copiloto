"""CVM — demonstrações financeiras oficiais, POINT-IN-TIME.

É a fundação do copiloto de decisão. Sem balanço não há tese verificável, não há preço teto,
não há nada.

**Por que a CVM e não o yfinance:** o Yahoo entrega o balanço de HOJE e revisa números
retroativamente — qualquer análise histórica com ele teria lookahead embutido. A CVM publica
o campo `DT_RECEB`: **a data em que o documento chegou**. Isso é point-in-time de verdade —
dá para saber exatamente o que estava público em cada data.

E o dividendo do Yahoo é **furado**: ele reporta 1 pagamento de R$ 0,1125 para a SAPR4 (o que
daria um preço teto de R$ 1,41 numa ação de R$ 7,22 — o sistema diria "nunca compre", em
silêncio e errado). A causa provável é o JCP, que é metade do que uma empresa brasileira
distribui. Aqui o dividendo vem do **fluxo de caixa auditado**.

QUATRO ARMADILHAS DO FORMATO, cada uma capaz de corromper tudo em silêncio:

1. **Acumulado × trimestre isolado.** O ITR traz OS DOIS na mesma tabela. A Petrobras aparece
   com R$ 370 bi de receita (acumulado até setembro) E R$ 128 bi (só o 3º tri). Somar os dois
   triplica o lucro ao longo do ano. `DT_INI_EXERC` é quem distingue.

2. **ORDEM_EXERC.** Cada linha vem duplicada: `ÚLTIMO` (o período atual) e `PENÚLTIMO` (o
   comparativo do ano anterior). Pegar os dois duplica tudo.

3. **ESCALA_MOEDA.** Uns reportam em `MIL`, outros em `UNIDADE`. Ignorar isso erra por 1000×.

4. **VERSÃO.** A empresa republica o mesmo trimestre (v1, v2, v3) quando corrige. Para
   point-in-time honesto, o que vale é a versão disponível NAQUELA data — não a última.
"""

from __future__ import annotations

import io
import re
import zipfile

import httpx
import pandas as pd

from app.core.config import DATA_DIR

BASE = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC"
CACHE = DATA_DIR / "cvm"
CACHE_VERSAO = "v2"  # muda quando o parse muda → invalida em vez de servir dado velho

# Ticker válido na B3: 4 letras + 1-2 dígitos. O FCA vem com lixo ('0', '1545-8', 'ADR').
RE_TICKER = re.compile(r"^[A-Z]{4}\d{1,2}$")

# As demonstrações que interessam.
#
# `con` = consolidado, `ind` = individual. Lemos OS DOIS e preferimos o consolidado quando
# existe. Empresa sem subsidiária — a SANEPAR, por exemplo — **só publica a individual**, e
# ler apenas `_con` a faria sumir do sistema inteiro sem nenhum erro aparecer.
DEMONSTRACOES = {
    "DRE": ["DRE_con", "DRE_ind"],        # resultado: receita, EBIT, lucro
    "BPA": ["BPA_con", "BPA_ind"],        # balanço — ativo
    "BPP": ["BPP_con", "BPP_ind"],        # balanço — passivo e patrimônio líquido
    "DFC": ["DFC_MI_con", "DFC_MI_ind"],  # fluxo de caixa → é daqui que sai o DIVIDENDO
}


def _url(doc: str, ano: int) -> str:
    return f"{BASE}/{doc}/DADOS/{doc.lower()}_cia_aberta_{ano}.zip"


def _baixar(doc: str, ano: int) -> zipfile.ZipFile | None:
    try:
        r = httpx.get(_url(doc, ano), timeout=300.0, follow_redirects=True)
        r.raise_for_status()
    except Exception as exc:  # noqa: BLE001 — ano faltante não derruba o lote
        print(f"  ! {doc} {ano}: {exc}")
        return None
    return zipfile.ZipFile(io.BytesIO(r.content))


def _csv(z: zipfile.ZipFile, nome: str) -> pd.DataFrame:
    if nome not in z.namelist():
        return pd.DataFrame()
    return pd.read_csv(z.open(nome), sep=";", encoding="latin-1", dtype=str)


# --------------------------------------------------------------------- mapa de ticker


def mapa_tickers(ano: int = 2025, force: bool = False) -> pd.DataFrame:
    """CNPJ → ticker, oficial (Formulário Cadastral). A CVM não conhece "PETR4" nos balanços."""
    CACHE.mkdir(parents=True, exist_ok=True)
    p = CACHE / f"tickers_{CACHE_VERSAO}.parquet"
    if p.exists() and not force:
        return pd.read_parquet(p)

    z = _baixar("FCA", ano)
    if z is None:
        return pd.DataFrame()

    vm = _csv(z, f"fca_cia_aberta_valor_mobiliario_{ano}.csv")
    if vm.empty:
        return pd.DataFrame()

    vm = vm[vm["Valor_Mobiliario"].str.contains("Ações|Units", na=False, regex=True)]
    vm = vm[vm["Codigo_Negociacao"].notna()]
    vm = vm[vm["Codigo_Negociacao"].str.strip().str.upper().apply(
        lambda t: bool(RE_TICKER.match(t))
    )]

    out = (
        vm.assign(
            ticker=vm["Codigo_Negociacao"].str.strip().str.upper(),
            cnpj=vm["CNPJ_Companhia"].str.strip(),
            empresa=vm["Nome_Empresarial"].str.strip(),
            tipo=vm["Valor_Mobiliario"].str.strip(),
        )[["ticker", "cnpj", "empresa", "tipo"]]
        .drop_duplicates("ticker")
        .reset_index(drop=True)
    )

    out = pd.concat([out, _irmaos(out)], ignore_index=True).drop_duplicates("ticker")
    out.to_parquet(p, index=False)
    return out.reset_index(drop=True)


def _irmaos(mapa: pd.DataFrame) -> pd.DataFrame:
    """Deriva os papéis que o FCA esquece.

    O FCA da Klabin lista **só o KLBN11** (a unit) — KLBN3 e KLBN4 simplesmente não estão lá.
    A base oficial é incompleta neste ponto.

    A convenção da B3 resolve: mesmo prefixo de 4 letras, `3` = ON, `4` = PN, `11` = unit.
    Derivamos os irmãos e **validamos contra o COTAHIST**, que sabe quais tickers de fato
    negociaram — assim não inventamos um papel que não existe.
    """
    from app.ingest.cotahist import CACHE as COTA_CACHE

    reais: set[str] = set()
    if COTA_CACHE.exists():
        for f in COTA_CACHE.glob("*.parquet"):
            reais |= set(pd.read_parquet(f, columns=["ticker"])["ticker"].unique())
    if not reais:
        return pd.DataFrame(columns=mapa.columns)  # sem COTAHIST, não arrisca

    conhecidos = set(mapa["ticker"])
    novos = []
    for _, r in mapa.iterrows():
        prefixo = r["ticker"][:4]
        for sufixo in ("3", "4", "5", "6", "11"):
            tk = f"{prefixo}{sufixo}"
            if tk not in conhecidos and tk in reais:
                novos.append(
                    {"ticker": tk, "cnpj": r["cnpj"], "empresa": r["empresa"],
                     "tipo": "derivado (FCA incompleto)"}
                )
                conhecidos.add(tk)

    return pd.DataFrame(novos) if novos else pd.DataFrame(columns=mapa.columns)


# --------------------------------------------------------------------- demonstrações


def _limpar(df: pd.DataFrame, doc: str, ano: int) -> pd.DataFrame:
    """Aplica as quatro defesas do cabeçalho deste módulo."""
    if df.empty:
        return df

    # (2) só o exercício ATUAL — PENÚLTIMO é o comparativo do ano anterior e duplicaria tudo
    d = df[df["ORDEM_EXERC"].str.upper().str.startswith("ÚLT", na=False)].copy()
    if d.empty:
        return pd.DataFrame()

    # (3) escala: MIL × 1000. Ignorar isso erra por três ordens de grandeza.
    escala = d["ESCALA_MOEDA"].str.upper().str.strip()
    fator = escala.map({"MIL": 1_000.0, "UNIDADE": 1.0}).fillna(1.0)
    d["valor"] = pd.to_numeric(d["VL_CONTA"], errors="coerce") * fator

    d["dt_refer"] = pd.to_datetime(d["DT_REFER"], errors="coerce")
    d["dt_fim"] = pd.to_datetime(d["DT_FIM_EXERC"], errors="coerce")
    # (1) o BALANÇO (BPA/BPP) é uma foto: não tem DT_INI. O RESULTADO (DRE/DFC) é um filme.
    d["dt_ini"] = (
        pd.to_datetime(d["DT_INI_EXERC"], errors="coerce")
        if "DT_INI_EXERC" in d.columns
        else pd.NaT
    )
    d["versao"] = pd.to_numeric(d["VERSAO"], errors="coerce").fillna(1).astype(int)

    return d.rename(
        columns={"CNPJ_CIA": "cnpj", "DENOM_CIA": "empresa",
                 "CD_CONTA": "conta", "DS_CONTA": "descricao"}
    )[
        ["cnpj", "empresa", "dt_refer", "dt_ini", "dt_fim", "versao",
         "conta", "descricao", "valor"]
    ].assign(doc=doc, ano=ano)


def fetch_ano(ano: int, force: bool = False) -> pd.DataFrame:
    """Um ano de ITR (trimestres) + DFP (anual), já limpo. Cache: o passado não muda."""
    CACHE.mkdir(parents=True, exist_ok=True)
    p = CACHE / f"{ano}_{CACHE_VERSAO}.parquet"
    if p.exists() and not force:
        return pd.read_parquet(p)

    partes = []
    for tipo in ("ITR", "DFP"):
        z = _baixar(tipo, ano)
        if z is None:
            continue

        # DT_RECEB: a DATA DE PUBLICAÇÃO. É o que torna tudo isto point-in-time.
        mestre = _csv(z, f"{tipo.lower()}_cia_aberta_{ano}.csv")
        receb = pd.DataFrame()
        if not mestre.empty:
            receb = mestre.assign(
                cnpj=mestre["CNPJ_CIA"].str.strip(),
                dt_refer=pd.to_datetime(mestre["DT_REFER"], errors="coerce"),
                versao=pd.to_numeric(mestre["VERSAO"], errors="coerce").fillna(1).astype(int),
                dt_receb=pd.to_datetime(mestre["DT_RECEB"], errors="coerce"),
            )[["cnpj", "dt_refer", "versao", "dt_receb"]].drop_duplicates()

        for nome, sufixos in DEMONSTRACOES.items():
            por_escopo: dict[str, pd.DataFrame] = {}
            for sufixo in sufixos:
                bruto = _csv(z, f"{tipo.lower()}_cia_aberta_{sufixo}_{ano}.csv")
                d = _limpar(bruto, nome, ano)
                if not d.empty:
                    por_escopo["con" if sufixo.endswith("con") else "ind"] = d

            if not por_escopo:
                continue

            con = por_escopo.get("con", pd.DataFrame())
            ind = por_escopo.get("ind", pd.DataFrame())

            # Preferimos o consolidado. A individual entra só para quem NÃO publica
            # consolidado (empresa sem subsidiária, como a Sanepar).
            if not con.empty and not ind.empty:
                so_ind = ind[~ind["cnpj"].isin(set(con["cnpj"]))]
                d = pd.concat([con, so_ind], ignore_index=True)
            else:
                d = con if not con.empty else ind

            if not receb.empty:
                d = d.merge(receb, on=["cnpj", "dt_refer", "versao"], how="left")
            d["origem"] = tipo
            partes.append(d)

        # Quantidade de ações — sem ela não existe lucro POR AÇÃO, logo não existe preço teto.
        cc = _csv(z, f"{tipo.lower()}_cia_aberta_composicao_capital_{ano}.csv")
        if not cc.empty:
            c = cc.assign(
                cnpj=cc["CNPJ_CIA"].str.strip(),
                empresa=cc["DENOM_CIA"].str.strip(),
                dt_refer=pd.to_datetime(cc["DT_REFER"], errors="coerce"),
                versao=pd.to_numeric(cc["VERSAO"], errors="coerce").fillna(1).astype(int),
            )
            for col, conta, desc in (
                ("QT_ACAO_ORDIN_CAP_INTEGR", "ACOES_ON", "Ações ordinárias"),
                ("QT_ACAO_PREF_CAP_INTEGR", "ACOES_PN", "Ações preferenciais"),
                ("QT_ACAO_TOTAL_TESOURO", "ACOES_TESOURO", "Ações em tesouraria"),
            ):
                if col not in c.columns:
                    continue
                linha = c.assign(
                    conta=conta, descricao=desc,
                    valor=pd.to_numeric(c[col], errors="coerce"),
                    dt_ini=pd.NaT, dt_fim=c["dt_refer"], doc="CAP", ano=ano, origem=tipo,
                )[["cnpj", "empresa", "dt_refer", "dt_ini", "dt_fim", "versao",
                   "conta", "descricao", "valor", "doc", "ano", "origem"]]
                if not receb.empty:
                    linha = linha.merge(receb, on=["cnpj", "dt_refer", "versao"], how="left")
                partes.append(linha)

    if not partes:
        return pd.DataFrame()

    out = pd.concat(partes, ignore_index=True).dropna(subset=["valor"])
    out.to_parquet(p, index=False, compression="zstd")
    return out


def load(anos: list[int]) -> pd.DataFrame:
    ano_atual = pd.Timestamp.now().year
    partes = []
    for a in anos:
        # O ano corrente ainda está crescendo — rebaixa sempre.
        d = fetch_ano(a, force=(a == ano_atual))
        if not d.empty:
            partes.append(d)
    return pd.concat(partes, ignore_index=True) if partes else pd.DataFrame()
