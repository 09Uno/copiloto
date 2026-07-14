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

- [x] **Fase 0** — ingestão: 20 anos da B3 (COTAHIST oficial), EUA e cripto
- [x] **Fase 1** — motor de indicadores (`app/engine/`, módulo puro, testado)
- [x] **Fase 2** — backtest ← **o portão de decisão. E ele reprovou.**
- [ ] Fase 3+ — ferramenta de análise (ver abaixo)

---

## ⛔ O VEREDITO: não há sinal a extrair

**Foi para isto que o portão da Fase 2 existia, e ele fez o trabalho dele.** Antes de existirem
dashboard, worker em VPS e alertas — que teriam sido meses construídos sobre uma premissa falsa.

### Nenhuma estratégia tem borda (out-of-sample, líquido de custos)

| Estratégia | Fora da amostra |
|---|---|
| Reversão · cripto 15m | **−0,644R** — o custo (0,30%) come metade do risco: o stop fica a 0,7% do preço |
| Reversão · EUA diário | +0,065R, **t = 0,77** → ruído. E perde do buy & hold |
| Cross-sectional · B3 | −0,015R · o grid de **81 combinações** não salvou |
| Momentum 12-1 long-short | −0,014R |
| Momentum 12-1 long-only | −0,054R |
| **Carteira** momentum (sem stop) | **perde para comprar o universo inteiro** — 11,3 p.p./ano |

### E o problema não é a regra: é que **não há informação no dado**

Testado direto, com AUC e calibração por decil (0,500 = cara ou coroa):

| Fonte | Observações | AUC fora da amostra |
|---|---|---|
| Features de **preço** | 936.392 | 0,487 – 0,515 |
| **Sentimento** de notícia (GDELT) | 475.966 artigos | 0,494 – 0,504 |

O teste **detecta** informação quando ela existe (controle positivo: feature que conhece o
futuro → AUC 0,80). Aqui não há o que detectar.

> **Consequência de produto:** uma tela mostrando *"68% de chance"* estaria **inventando o
> número**. O histórico diz ~47% para qualquer setup. Convicção falsa é pior que nenhuma
> ferramenta.

### O que a evidência produziu de positivo

Comprar as **~120 mais líquidas em peso igual** e rebalancear **bateu** todas as estratégias,
com **metade do drawdown**. Diversificação simples vence a tentativa de escolher — medido em
16 anos de dado oficial, sem viés de sobrevivência, com custo de giro.

---

## Para onde o projeto vai

O que **não depende de previsão**, e por isso continua de pé:

- **Carteira** — P&L do dia/semana/mês, por moeda, e o **drawdown real**
- **Triagem fundamentalista** (`dands valor`, já funciona) — Graham, Gordon, múltiplos contra a
  própria história do papel, ROE como antídoto da armadilha de valor
- **Alertas de FATO**, não de previsão — *"caiu 18% desde a sua compra"*, *"saiu balanço"*
- **Benchmark** — a sua curva real contra o índice. A pergunta que quase ninguém se faz.
- **O laboratório** — `dands backtest` / `informacao`: mede qualquer hipótese futura, sua ou de
  terceiros. Da próxima vez que alguém te vender uma estratégia, você mede em vez de acreditar.

## Banco

Supabase (Postgres gerenciado) — nada a instalar na máquina. A URI vai em `backend/.env`,
que **nunca é versionado**. `infra/schema.sql` é Postgres puro e idempotente.
