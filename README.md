# day-and-swing

Motor quantamental de uso próprio: reversão à média com filtro de regime, validado por backtest
antes de operar. Cripto (Binance, tempo real), ações B3 e EUA (EOD).

| Documento | Papel |
|---|---|
| [SPEC.md](SPEC.md) | **O que** o motor calcula — features, regra de sinal, risco, triple-barrier |
| [ARCHITECTURE.md](ARCHITECTURE.md) | **Como** é montado — stack, processos, schema, endpoints |
| [development_plan.md](development_plan.md) | **Em que ordem** construir, e o portão de decisão da Fase 2 |

## Setup

```bash
cd backend
python -m venv .venv
.venv/Scripts/activate        # Windows;  source .venv/bin/activate no Linux
pip install -e ".[dev]"
cp .env.example .env          # e preencha DATABASE_URL com a URI do Supabase
```

## Uso

```bash
dands backfill --anos 3       # baixa o histórico (idempotente; rodar de novo só busca o que falta)
dands backfill --market CRYPTO
dands doctor                  # cobertura e gaps — RODAR ANTES de confiar no dado
dands show BTCUSDT 15m

dands db init                 # aplica infra/schema.sql no Supabase (idempotente)
dands db load                 # carrega o Parquet no Postgres (upsert por vela)
dands db account BRL --saldo 10000 --risco 1.0   # banca por moeda + sizing (SPEC §8)

pytest
```

## Onde o dado mora (duas camadas, de propósito)

**Aterrissagem — Parquet local.** `data/ohlcv/{mercado}/{ticker}/{timeframe}.parquet`: um arquivo
por série, tz-aware em UTC, sem duplicata, ordenado. Invariantes garantidas por
`app/ingest/store.py` e cobertas por teste. É a fonte da verdade do dado bruto — imutável e
reprodutível via `dands backfill` (por isso `data/` não vai pro git).

**Serviço — Supabase (Postgres).** Alimentado a partir do Parquet por `dands db load`. É dele
que a API e o dashboard leem (Fase 3).

Não é redundância: o backtest da Fase 2 relê o histórico centenas de vezes no grid search de
hiperparâmetros, e **não deve depender de rede nem de banco no ar** — ele lê o Parquet direto.

## Estado

- [x] **Fase 0** — ingestão e histórico íntegro (3 anos: 15m de cripto, EOD de ações)
- [ ] **Fase 1** — motor de indicadores (`app/engine/`, módulo puro, sem I/O)
- [ ] **Fase 2** — backtest ← **portão de decisão do projeto**
- [ ] Fase 3+ — motor em produção, dashboard, sentimento, ML

> A Fase 2 é o único momento barato de descobrir que a estratégia não tem borda.
> Se nenhuma combinação mercado × timeframe tiver expectância positiva **líquida de custos
> e fora da amostra**, o projeto para ali e a regra é repensada — não se constrói o resto
> por cima de uma borda que não existe.

## Banco

Supabase (Postgres gerenciado) — nada a instalar na máquina. A URI vai em `backend/.env`,
que **nunca é versionado**. `infra/schema.sql` é Postgres puro e idempotente.
