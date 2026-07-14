"""Fundamentos derivados do balanço da CVM — POINT-IN-TIME. Módulo puro.

Transforma o balanço bruto nas métricas que sustentam a tese e o preço teto:
LPA, VPA, DPA, ROE, margem, dívida líquida/EBITDA, payout.

**A armadilha central: acumulado × trimestre isolado.**

O ITR traz OS DOIS na mesma tabela. A Petrobras aparece com R$ 370 bi de receita (acumulado
até setembro) E R$ 128 bi (só o 3º tri). Quem soma sem separar vê o lucro triplicar sozinho
ao longo do ano — e conclui que a empresa está crescendo quando ela está parada.

Para os últimos 12 meses (LPA, DPA, ROE) o que se quer é a soma de **quatro trimestres
isolados**. O sinal para reconhecê-los: `dt_fim − dt_ini ≈ 3 meses`.

**O 4º trimestre não existe no ITR.** A CVM só recebe ITR de Q1, Q2 e Q3; o Q4 vem dentro do
DFP (anual, acumulado de 12 meses). Então:

    Q4 = ano cheio (DFP) − acumulado até setembro (ITR do 3º tri)

Esquecer isso faz o 4º trimestre sumir — e o "últimos 12 meses" vira 9 meses, subestimando
o lucro em ~25% de forma permanente e silenciosa.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

RECEITA = "3.01"  # "Receita de Venda" na indústria, "Receitas de Intermediação" no banco — 3.01 nos dois
EBIT = "3.05"     # resultado antes do resultado financeiro e dos tributos (não se aplica a banco)

# **O LUCRO NÃO TEM CÓDIGO FIXO.** É `3.11` na Petrobras e `3.09` no ITAÚ — o banco tem a DRE
# mais curta (não separa resultado financeiro). Buscar por código deixa o Itaú SEM LUCRO, e o
# sistema simplesmente não mostraria LPA nem ROE do maior banco do país, sem erro nenhum.
#
# E a descrição varia: "Lucro/Prejuízo CONSOLIDADO do Período" (Petrobras, Itaú) mas
# "Lucro/Prejuízo do Período" na SANEPAR — que publica demonstração individual. Exigir a
# palavra "consolidado" apagaria o lucro dela.
#
# E a separação também varia: "Lucro/Prejuízo" (Petrobras, Vale) mas "Lucro OU Prejuízo"
# (Bradesco, Banco do Brasil).
#
# Ancorado nas duas pontas para não capturar "Lucro ou Prejuízo das Operações Continuadas",
# "Lucro ou Prejuízo antes das Participações" nem "Lucro Básico por Ação".
RE_LUCRO = r"^lucro\s*(?:ou|/)\s*preju[íi]zo.*(?:per[íi]odo|exerc[íi]cio)$"

CAIXA = "1.01.01"
DIVIDA_CURTO = "2.01.04"      # empréstimos e financiamentos — circulante
DIVIDA_LONGO = "2.02.01"      # empréstimos e financiamentos — não circulante

# **BANCO TEM PLANO DE CONTAS PRÓPRIO.** A conta "2.03" é "Patrimônio Líquido Consolidado" na
# Petrobras, mas é "Passivos Financeiros ao Custo Amortizado" no ITAÚ (R$ 2,4 TRILHÕES) e
# "Provisões" no BRADESCO. Buscar patrimônio por CÓDIGO dá o número errado por duas ordens de
# grandeza — e ainda por cima um número plausível o bastante para passar despercebido.
# Por descrição, funciona nos dois.
RE_PATRIMONIO = r"^patrim[ôo]nio l[íi]quido"

# Dividendo: só o que é PAGO, e só no FINANCIAMENTO (conta 6.03.*).
#
# A TAESA e o WEG RECEBEM dividendos de controladas (conta 6.01.02.*, entrada de caixa) e
# PAGAM dividendos aos acionistas (6.03.*, saída). Somar os dois os faz **se cancelar** — o
# payout da Taesa despencava para 19% quando o real é ~90%. O sistema diria que ela mal
# distribui, e o preço teto sairia 5x abaixo do correto.
GRUPO_FINANCIAMENTO = "6.03"
RE_DIVIDENDO = r"dividend|juros sobre.*capital|jcp"

# **E não é seu.** A VALE paga "Dividendos e JCP aos acionistas NÃO CONTROLADORES" — que é o
# minoritário das SUBSIDIÁRIAS dela, não o acionista da Vale. Somar isso inflava o payout dela
# para 249%. O dividendo que interessa ao preço teto é o que chega em VOCÊ.
RE_NAO_CONTROLADOR = r"n[ãa]o[- ]controlador|minorit"

# Banco não tem "EBIT" nem "dívida líquida" no sentido usual — o passivo dele é o negócio.
RE_FINANCEIRA = r"intermedia[çc][ãa]o financeira|receitas? de juros"

TRIMESTRE_DIAS = (80, 100)  # ~3 meses, com folga para o calendário

# Companhia listada na B3 não tem menos que isto em ações. Abaixo do piso, o número está em
# MILHARES — e a CVM não é consistente: a Petrobras reporta 7.442.231.382 (unidades) e a
# TAESA reporta 590.714 (milhares). Sem detectar, o LPA da TAESA sai 1000x inflado.
PISO_ACOES = 50_000_000


@dataclass(frozen=True)
class Fundamento:
    ticker: str
    empresa: str
    data_base: pd.Timestamp    # trimestre a que se refere
    data_publicacao: pd.Timestamp  # quando virou público — é o que impede o lookahead

    lucro_12m: float | None
    receita_12m: float | None
    ebit_12m: float | None
    dividendos_12m: float | None   # dividendos + JCP PAGOS (do fluxo de caixa, auditado)

    patrimonio: float | None
    divida_liquida: float | None
    acoes: float | None
    financeira: bool = False  # banco/seguradora: EBIT e dívida líquida não se aplicam

    @property
    def lpa(self) -> float | None:
        return self.lucro_12m / self.acoes if self.acoes and self.lucro_12m else None

    @property
    def vpa(self) -> float | None:
        return self.patrimonio / self.acoes if self.acoes and self.patrimonio else None

    @property
    def dpa(self) -> float | None:
        """Dividendo por ação — a base do PREÇO TETO. Vem do caixa, não do Yahoo."""
        if not self.acoes or self.dividendos_12m is None:
            return None
        return abs(self.dividendos_12m) / self.acoes

    @property
    def roe(self) -> float | None:
        if not self.patrimonio or self.patrimonio <= 0 or self.lucro_12m is None:
            return None
        return self.lucro_12m / self.patrimonio

    @property
    def payout(self) -> float | None:
        """Quanto do lucro virou dividendo. Acima de 100% = distribui mais do que ganha."""
        if not self.lucro_12m or self.lucro_12m <= 0 or self.dividendos_12m is None:
            return None
        return abs(self.dividendos_12m) / self.lucro_12m

    @property
    def divida_ebit(self) -> float | None:
        if self.divida_liquida is None or not self.ebit_12m or self.ebit_12m <= 0:
            return None
        return self.divida_liquida / self.ebit_12m

    @property
    def margem(self) -> float | None:
        if not self.receita_12m or self.receita_12m <= 0 or self.lucro_12m is None:
            return None
        return self.lucro_12m / self.receita_12m


def _serie_vazia() -> pd.Series:
    """Índice de DATAS mesmo quando vazia — senão a comparação com Timestamp explode."""
    return pd.Series([], index=pd.DatetimeIndex([]), dtype=float)


def _e_trimestre(dt_ini: pd.Timestamp, dt_fim: pd.Timestamp) -> bool:
    """Trimestre ISOLADO (~3 meses) e não acumulado do ano."""
    if pd.isna(dt_ini) or pd.isna(dt_fim):
        return False
    dias = (dt_fim - dt_ini).days
    return TRIMESTRE_DIAS[0] <= dias <= TRIMESTRE_DIAS[1]


def _fluxo_trimestral(df: pd.DataFrame, conta: str | None, regex: str | None = None) -> pd.Series:
    """Série de trimestres ISOLADOS para uma conta de RESULTADO (DRE/DFC).

    **O ponto delicado: a maioria das empresas só publica o ACUMULADO do ano no fluxo de caixa.**
    Exigir que a empresa reporte o trimestre isolado faz o dividendo da SANEPAR virar zero — e
    o mesmo aconteceria com quase todas. O sistema diria "não paga dividendo" a respeito de uma
    empresa que paga, e o preço teto seria zero.

    A reconstrução por DIFERENÇA do acumulado é geral e resolve para todo mundo:

        Q1 = acum(mar)
        Q2 = acum(jun) − acum(mar)
        Q3 = acum(set) − acum(jun)
        Q4 = acum(dez, do DFP anual) − acum(set)      ← o 4º tri não existe no ITR

    Quando a empresa PUBLICA o trimestre isolado (a DRE costuma trazer os dois), preferimos o
    número dela ao nosso cálculo.
    """
    d = df[df["conta"] == conta] if conta else df[
        df["descricao"].str.contains(regex, case=False, na=False, regex=True)
    ]
    if d.empty:
        return _serie_vazia()

    # Um dividendo aparece em VÁRIAS linhas (dividendos E JCP, e às vezes em contas diferentes
    # no mesmo trimestre). Soma por período.
    d = (
        d.groupby(["dt_ini", "dt_fim"], as_index=False)["valor"].sum()
        .dropna(subset=["dt_ini", "dt_fim"])
    )
    d["dias"] = (d["dt_fim"] - d["dt_ini"]).dt.days

    # "Year-to-date" = tudo que COMEÇA em janeiro, INCLUSIVE o 1º trimestre.
    #
    # Deixar o Q1 de fora da série acumulada (por ele ter "só" 90 dias) faz a diferença do Q2
    # partir de ZERO: `Q2 = acum(jun) − 0 = Q1 + Q2`. **O primeiro trimestre entra duas vezes**,
    # e o efeito se propaga por todo o ano. Foi o que inflou o dividendo da VALE (payout 249%).
    ytd = d[d["dt_ini"].dt.month <= 1].copy()

    isolados: dict[pd.Timestamp, float] = {}
    for ano, g in ytd.groupby(ytd["dt_fim"].dt.year):
        g = g.sort_values("dt_fim")
        anterior = 0.0
        for _, r in g.iterrows():
            isolados[r["dt_fim"]] = float(r["valor"]) - anterior
            anterior = float(r["valor"])
        del ano

    # O trimestre que a empresa PUBLICA isolado (a DRE costuma trazer os dois) tem precedência
    # sobre o nosso cálculo — é o número dela.
    publicados = d[d["dias"].between(*TRIMESTRE_DIAS) & (d["dt_ini"].dt.month > 1)]
    for _, r in publicados.iterrows():
        isolados[r["dt_fim"]] = float(r["valor"])

    if not isolados:
        return _serie_vazia()
    return pd.Series(isolados).sort_index()


def _ultimo(df: pd.DataFrame, conta: str, ate: pd.Timestamp) -> float | None:
    """Último valor de uma conta de BALANÇO (é foto, não filme — soma seria absurdo)."""
    d = df[(df["conta"] == conta) & (df["dt_refer"] <= ate)]
    if d.empty:
        return None
    return float(d.sort_values("dt_refer")["valor"].iloc[-1])


def _ultimo_por_descricao(df: pd.DataFrame, regex: str, ate: pd.Timestamp) -> float | None:
    """Busca a conta pela DESCRIÇÃO — a defesa contra o plano de contas dos bancos.

    Entre várias linhas que casam, fica a de **código mais curto**: é a conta de topo
    ("2.03 Patrimônio Líquido Consolidado") e não uma subconta ("2.03.05 Reservas de Lucros").
    """
    d = df[
        df["descricao"].str.strip().str.contains(regex, case=False, na=False, regex=True)
        & (df["dt_refer"] <= ate)
    ]
    if d.empty:
        return None

    ultimo = d[d["dt_refer"] == d["dt_refer"].max()].copy()
    ultimo["nivel"] = ultimo["conta"].str.count(r"\.")
    topo = ultimo.sort_values("nivel").iloc[0]
    return float(topo["valor"])


def _normalizar_acoes(total: float | None) -> float | None:
    """Corrige a escala. Ver PISO_ACOES: a CVM mistura unidades e milhares entre empresas."""
    if not total or total <= 0:
        return None
    return total * 1000.0 if total < PISO_ACOES else total


def calcular(
    painel: pd.DataFrame,
    ticker: str,
    empresa: str,
    ate: pd.Timestamp | None = None,
) -> Fundamento | None:
    """Fundamentos de UMA empresa, com o que estava público até `ate`.

    `painel` = saída de `cvm.load()` filtrada por CNPJ.

    **O filtro por `dt_receb` é o que torna isto honesto.** Usar `dt_refer` (o trimestre a que
    o balanço se refere) deixaria o sistema "saber" em 30/09 um resultado que só foi publicado
    em 12/11 — seis semanas de lookahead, exatamente o erro que invalida análise histórica.
    """
    if painel.empty:
        return None

    d = painel.copy()
    if ate is not None:
        pub = d["dt_receb"].fillna(d["dt_refer"])
        d = d[pub <= ate]
    if d.empty:
        return None

    # (4) versão: fica a mais recente JÁ PUBLICADA de cada trimestre
    d = (
        d.sort_values("versao")
        .drop_duplicates(subset=["dt_refer", "doc", "conta", "dt_ini", "dt_fim"], keep="last")
    )

    dre = d[d["doc"] == "DRE"]
    bpp = d[d["doc"] == "BPP"]
    bpa = d[d["doc"] == "BPA"]
    dfc = d[d["doc"] == "DFC"]
    cap = d[d["doc"] == "CAP"]

    ref = d["dt_refer"].max()
    pub_ref = d.loc[d["dt_refer"] == ref, "dt_receb"].max()

    def soma12m(s: pd.Series) -> float | None:
        """Últimos 12 meses = soma dos 4 trimestres ISOLADOS mais recentes."""
        if s.empty:
            return None
        s = s[s.index <= ref]
        return float(s.tail(4).sum()) if len(s) >= 4 else None

    # Lucro por DESCRIÇÃO — é 3.11 na Petrobras e 3.09 no Itaú (ver RE_LUCRO).
    # Filtramos as subcontas (ex.: "das Operações Descontinuadas") pelo nível do código.
    dre_lucro = dre[dre["conta"].str.count(r"\.") <= 1]
    lucro = soma12m(_fluxo_trimestral(dre_lucro, None, RE_LUCRO))
    receita = soma12m(_fluxo_trimestral(dre, RECEITA))

    # Só o dividendo PAGO (financiamento, 6.03.*) e só o que chega AO ACIONISTA DA COMPANHIA.
    #   · o recebido de controladas (6.01.*) é entrada de caixa e cancelaria a saída;
    #   · o pago a não controladores é do minoritário das subsidiárias, não seu.
    dfc_pago = dfc[
        dfc["conta"].str.startswith(GRUPO_FINANCIAMENTO)
        & ~dfc["descricao"].str.contains(
            RE_NAO_CONTROLADOR, case=False, na=False, regex=True
        )
    ]
    div = soma12m(_fluxo_trimestral(dfc_pago, None, RE_DIVIDENDO))

    # Banco: o passivo É o negócio. "EBIT" e "dívida líquida" não significam nada nele —
    # calcular assim mesmo produziria uma alavancagem de 32x e um alarme falso permanente.
    financeira = bool(
        dre["descricao"].str.contains(RE_FINANCEIRA, case=False, na=False, regex=True).any()
    )

    ebit = None if financeira else soma12m(_fluxo_trimestral(dre, EBIT))

    # Patrimônio por DESCRIÇÃO, nunca por código — ver RE_PATRIMONIO.
    patrimonio = _ultimo_por_descricao(bpp, RE_PATRIMONIO, ref)

    divida_liq = None
    if not financeira:
        caixa = _ultimo(bpa, CAIXA, ref) or 0.0
        dcp = _ultimo(bpp, DIVIDA_CURTO, ref) or 0.0
        dlp = _ultimo(bpp, DIVIDA_LONGO, ref) or 0.0
        divida_liq = (dcp + dlp) - caixa if (dcp or dlp) else None

    on = _ultimo(cap, "ACOES_ON", ref) or 0.0
    pn = _ultimo(cap, "ACOES_PN", ref) or 0.0
    tesouro = _ultimo(cap, "ACOES_TESOURO", ref) or 0.0
    # Ação em tesouraria não recebe dividendo e não conta no lucro por ação.
    acoes = _normalizar_acoes(on + pn - tesouro)

    return Fundamento(
        ticker=ticker, empresa=empresa,
        data_base=ref, data_publicacao=pub_ref if pd.notna(pub_ref) else ref,
        lucro_12m=lucro, receita_12m=receita, ebit_12m=ebit, dividendos_12m=div,
        patrimonio=patrimonio, divida_liquida=divida_liq, acoes=acoes,
        financeira=financeira,
    )
