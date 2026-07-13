"""Universo de ativos monitorados.

**Quant de ações é cross-sectional por natureza.** Não se extraem centenas de sinais de uma
ação — extraem-se poucos sinais de centenas de ações. Com 7 papéis e 3 anos, o motor produziu
13 sinais no total: amostra que não permite concluir nada. Com ~190 papéis e 20 anos, passa a
haver material estatístico de verdade.

Ticker que morre (empresa deslistada, papel renomeado) devolve série vazia no ingestor e aparece
com 0 velas no `dands doctor`. Isso é tratado como caso normal, não como erro — a lista é um
retrato do mercado, e o mercado muda.

ATENÇÃO ao viés de sobrevivência: esta é a lista dos líquidos de HOJE. Um backtest que só olha
quem sobreviveu superestima o retorno (as empresas que quebraram sumiram da amostra). Para a
Fase 2 isso é uma limitação conhecida e declarada — corrigi-la exigiria a composição histórica
do índice, que não é gratuita.
"""

from __future__ import annotations

# --- B3: núcleo líquido (~IBrX-100). Sufixo .SA é o que o Yahoo usa.
B3_TICKERS = """
ABEV3 ALOS3 ASAI3 AURE3 AZUL4 B3SA3 BBAS3 BBDC3 BBDC4 BBSE3 BEEF3 BPAC11 BRAP4 BRFS3
BRKM5 CASH3 CMIG4 CMIN3 COGN3 CPFE3 CPLE6 CRFB3 CSAN3 CSMG3 CSNA3 CVCB3 CXSE3 CYRE3
DIRR3 DXCO3 EGIE3 ELET3 ELET6 EMBR3 ENEV3 ENGI11 EQTL3 EZTC3 FLRY3 GGBR4 GOAU4 GMAT3
HAPV3 HYPE3 IGTI11 IRBR3 ITSA4 ITUB4 JBSS3 KLBN11 LREN3 LWSA3 MGLU3 MRFG3 MRVE3 MULT3
NTCO3 PCAR3 PETR3 PETR4 PETZ3 POMO4 PRIO3 PSSA3 RADL3 RAIL3 RAIZ4 RDOR3 RECV3 RENT3
SANB11 SBSP3 SLCE3 SMFT3 SMTO3 STBP3 SUZB3 TAEE11 TIMS3 TOTS3 TRPL4 UGPA3 USIM5 VALE3
VAMO3 VBBR3 VIVA3 VIVT3 WEGE3 YDUQ3
""".split()

# --- EUA: S&P large caps líquidas.
US_TICKERS = """
AAPL MSFT NVDA AMZN GOOGL META TSLA LLY AVGO JPM XOM UNH V PG MA JNJ HD COST MRK ABBV
CVX ADBE PEP KO WMT CRM BAC TMO MCD CSCO ACN LIN ABT ORCL AMD DHR WFC TXN PM DIS INTU
VZ CAT IBM NEE CMCSA GE QCOM NOW UNP AMGN PFE SPGI RTX LOW ISRG HON T BKNG UBER GS ELV
PLD SYK BLK LMT TJX MDT SCHW MMC ADP CB ADI GILD MU C SBUX BSX AMT DE CI VRTX MO SO
PANW ZTS BA REGN CME EOG DUK SLB APD ITW BDX NKE CL EQIX MCK PGR AON CSX FDX
""".split()

# --- Cripto: onde o 15m é viável (único mercado com tempo real gratuito).
CRYPTO_TICKERS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT"]
