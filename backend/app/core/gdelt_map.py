"""Ticker → consulta no GDELT.

Só as empresas com **cobertura real de imprensa**. A Petrobras teve 13.651 notícias em 2024;
o Banco do Brasil, 262. Papel sem notícia não tem sentimento a medir — incluí-lo adiciona ruído
e finge uma amostra que não existe.

O escopo honesto do teste é este: **se o sentimento não informa nem para a Petrobras, com 13 mil
artigos por ano, não vai informar para ninguém.**

Uma frase entre aspas por empresa, sem `OR` e sem parênteses — testei as variantes contra a API
e essa é a que passa de forma confiável. `sourcecountry:BR` restringe à imprensa brasileira, que
é a que de fato move o papel na B3 (e resolve ambiguidade: "Vale" e "Gol" sozinhos casariam com
a preposição e com o esporte).
"""

from __future__ import annotations

CONSULTAS: dict[str, str] = {
    "PETR4.SA": '"Petrobras"',
    "VALE3.SA": '"mineradora Vale"',
    "ITUB4.SA": '"Itaú Unibanco"',
    "BBDC4.SA": '"Bradesco"',
    "BBAS3.SA": '"Banco do Brasil"',
    "ABEV3.SA": '"Ambev"',
    "WEGE3.SA": '"WEG"',
    "SUZB3.SA": '"Suzano"',
    "JBSS3.SA": '"JBS"',
    "EMBR3.SA": '"Embraer"',
    "MGLU3.SA": '"Magazine Luiza"',
    "LREN3.SA": '"Lojas Renner"',
    "RENT3.SA": '"Localiza"',
    "GGBR4.SA": '"Gerdau"',
    "CSNA3.SA": '"Companhia Siderúrgica Nacional"',
    "USIM5.SA": '"Usiminas"',
    "BRFS3.SA": '"BRF"',
    "NTCO3.SA": '"Natura"',
    "ELET3.SA": '"Eletrobras"',
    "CMIG4.SA": '"Cemig"',
    "EQTL3.SA": '"Equatorial Energia"',
    "SBSP3.SA": '"Sabesp"',
    "TIMS3.SA": '"TIM Brasil"',
    "AZUL4.SA": '"Azul Linhas Aéreas"',
    "PRIO3.SA": '"PetroRio"',
    "RDOR3.SA": '"Rede D\'Or"',
    "HAPV3.SA": '"Hapvida"',
    "COGN3.SA": '"Cogna"',
    "MRVE3.SA": '"MRV Engenharia"',
    "CYRE3.SA": '"Cyrela"',
    "IRBR3.SA": '"IRB Brasil"',
    "RAIL3.SA": '"Rumo Logística"',
    "CPFE3.SA": '"CPFL Energia"',
}

FILTRO_PAIS = "sourcecountry:BR"


def consulta(ticker: str) -> str | None:
    q = CONSULTAS.get(ticker)
    return f"{q} {FILTRO_PAIS}" if q else None
