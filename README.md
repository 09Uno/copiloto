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
```

## Uso

```bash
dands backfill --anos 3       # baixa o histórico (idempotente; rodar de novo só busca o que falta)
dands backfill --market CRYPTO
dands doctor                  # cobertura e gaps — RODAR ANTES de confiar no dado
dands show BTCUSDT 15m
pytest
```

## Onde o dado mora

Parquet em `data/ohlcv/{mercado}/{ticker}/{timeframe}.parquet` — um arquivo por série,
tz-aware em UTC, sem duplicata, ordenado. Invariantes garantidas por `app/ingest/store.py`
e cobertas por teste.

O dado bruto é **imutável e reprodutível** (`data/` não vai pro git). O Postgres da Fase 3
carrega a partir daqui; o backtest da Fase 2 lê o Parquet direto e **não precisa de banco no ar**.

## Estado

- [x] **Fase 0** — ingestão e histórico íntegro (3 anos: 15m de cripto, EOD de ações)
- [ ] **Fase 1** — motor de indicadores (`app/engine/`, módulo puro, sem I/O)
- [ ] **Fase 2** — backtest ← **portão de decisão do projeto**
- [ ] Fase 3+ — motor em produção, dashboard, sentimento, ML

> A Fase 2 é o único momento barato de descobrir que a estratégia não tem borda.
> Se nenhuma combinação mercado × timeframe tiver expectância positiva **líquida de custos
> e fora da amostra**, o projeto para ali e a regra é repensada — não se constrói o resto
> por cima de uma borda que não existe.

## Docker (Fase 3)

Ainda não instalado nesta máquina. Quando estiver:

```bash
docker compose up -d          # Postgres + TimescaleDB, schema aplicado de infra/schema.sql
```
