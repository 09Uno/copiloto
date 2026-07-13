# ARCHITECTURE — Motor Quantamental

Como o sistema é montado. Referência de implementação; o **que** ele calcula está em [SPEC.md](SPEC.md),
a **ordem** de construção em [development_plan.md](development_plan.md).

---

## 1. Stack

| Camada | Escolha | Papel |
|---|---|---|
| Frontend | Vite + React + Tailwind | Dashboard (Fase 4). Dark mode. |
| API | FastAPI + Uvicorn + SQLAlchemy async + Pydantic | Leitura do estado; auth por token único (uso próprio). |
| Workers | Python (pandas, numpy, scikit-learn) | Ingestão, cálculo de features, avaliação de desfecho. |
| Scheduler | **APScheduler** dentro do processo worker | Ver §2. |
| Banco | **Supabase** (Postgres gerenciado) | Camada de **serviço**: API e dashboard leem dele. |
| Dado bruto | **Parquet** local (`data/`) | Camada de **aterrissagem**: imutável, reprodutível. |

### Sobre o armazenamento em duas camadas
O dado bruto vive em Parquet e o Postgres é alimentado a partir dele (`dands db load`).
Não é redundância:
- o **backtest (Fase 2)** relê o histórico centenas de vezes no grid search de hiperparâmetros —
  ler Parquet local é instantâneo e não depende de rede nem de banco no ar;
- o dado bruto é **imutável**; não há motivo para ele nascer num banco transacional;
- reingerir 3 anos de klines a cada mudança de schema seria desperdício.

**Sem TimescaleDB e sem particionamento.** O Supabase não oferece a extensão, e — sendo honesto —
particionar ~300k linhas em uma ferramenta de uso próprio é otimização prematura: o Postgres puro
lida com dezenas de milhões de linhas sem suar. Um índice **BRIN** em `timestamp` (feito exatamente
para dado inserido em ordem cronológica) dá o ganho a custo quase zero. Se o volume justificar, particiona-se depois.

### Sobre o n8n (removido do desenho original)
O plano original usava n8n como scheduler chamando `POST /workers/prices/update`. **Isso não elimina a
necessidade de execução assíncrona — só a esconde:** o FastAPI processaria o lote inteiro dentro da
request e estouraria timeout assim que a watchlist crescesse. Começamos com **APScheduler no worker**
(um container a menos, uma superfície de falha a menos). Se o n8n entrar depois por conveniência visual,
o endpoint precisa **enfileirar e retornar `202`**, nunca processar em linha.

---

## 2. Processos

```
┌─────────────┐   HTTP    ┌──────────────┐
│  Frontend   │──────────>│   FastAPI    │  (só lê; não calcula)
└─────────────┘           └──────┬───────┘
                                 │
                          ┌──────▼───────┐
                          │  PostgreSQL  │
                          └──────▲───────┘
                                 │
┌────────────────────────────────┴────────────────────────────────┐
│                       Worker (APScheduler)                      │
│                                                                 │
│  ingest_crypto    WebSocket Binance, contínuo                   │
│  ingest_eod       agendado (fechamento B3 / NYSE)               │
│  compute_signals  a cada vela fechada → features → market_alerts│
│  close_alerts     alertas abertos → triple barrier → outcome    │
└─────────────────────────────────────────────────────────────────┘
```

A API **não calcula nada**. Todo cálculo vive no worker; a API serve o que já está persistido.

---

## 3. Layout do repositório

```
day-and-swing/
├── docker-compose.yml
├── backend/
│   ├── alembic/                 # migrações
│   ├── app/
│   │   ├── api/                 # rotas FastAPI
│   │   ├── core/                # config (hiperparâmetros do SPEC §7), db
│   │   ├── models/              # SQLAlchemy
│   │   ├── engine/              # ← módulo PURO, sem I/O (SPEC §2-§4)
│   │   │   ├── indicators.py    #   regressão, bandas, z-score, ATR
│   │   │   ├── regime.py        #   LATERAL | TENDENCIA | NERVOSO
│   │   │   ├── signals.py       #   regra de sinal + TP/SL + filtro R:R
│   │   │   └── barriers.py      #   triple barrier
│   │   ├── ingest/              # binance.py, yfinance_eod.py, brapi.py
│   │   ├── workers/             # jobs agendados
│   │   └── nlp/                 # Fase 5
│   ├── backtest/                # ← Fase 2. Roda offline, importa engine/
│   └── tests/
└── frontend/
```

**`engine/` é puro de propósito:** recebe um DataFrame, devolve features. Sem banco, sem rede.
É o que permite o backtest (Fase 2) e o motor em produção (Fase 3) rodarem **exatamente o mesmo
código** — se forem implementações diferentes, os resultados divergem e o backtest vira ficção.

---

## 4. Schema (DDL)

Decisões que diferem do rascunho inicial, e o porquê:

- **`TIMESTAMPTZ` em tudo, gravado em UTC.** B3 + EUA + cripto = três fusos, com o horário de verão
  americano mudando o offset duas vezes por ano. `TIMESTAMP` sem fuso é o bug que só aparece em
  novembro e corrompe meses de série histórica.
- **Sem `users` / `watchlists` / billing** — uso próprio. Watchlist é um booleano em `assets`.
- **`UNIQUE (ticker, market_type)`**, não `ticker` global: o mesmo ticker pode existir em mercados
  diferentes. `VARCHAR(20)` para caber opções da B3.
- **Chave natural em `asset_prices`** — `(asset_id, timeframe, timestamp)` já é a PK; o `BIGSERIAL`
  era um índice a mais sem função.
- **`model_version` / `engine_version` em todo score gerado.** Sem isso, retreinar o modelo de
  sentimento invalida silenciosamente o histórico e o dataset de treino vira uma mistura inútil de gerações.
- **`alert_evidence`** — liga o alerta aos posts que o motivaram. Sem essa tabela, a tela de
  justificativa é literalmente não implementável.
- **Particionamento por tempo desde o início.** Migrar depois dói.

```sql
CREATE TABLE assets (
    id            SERIAL PRIMARY KEY,
    ticker        VARCHAR(20) NOT NULL,
    market_type   VARCHAR(20) NOT NULL,           -- 'B3' | 'US' | 'CRYPTO'
    name          VARCHAR(120) NOT NULL,
    is_watchlist  BOOLEAN NOT NULL DEFAULT FALSE,
    timeframes    TEXT[] NOT NULL DEFAULT '{1d}', -- timeframes habilitados
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_asset UNIQUE (ticker, market_type)
);

CREATE TABLE asset_prices (
    asset_id    INT NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
    timeframe   VARCHAR(5) NOT NULL,              -- '15m' | '1d'
    timestamp   TIMESTAMPTZ NOT NULL,             -- SEMPRE UTC
    open_price  NUMERIC(18, 8) NOT NULL,
    high_price  NUMERIC(18, 8) NOT NULL,
    low_price   NUMERIC(18, 8) NOT NULL,
    close_price NUMERIC(18, 8) NOT NULL,
    volume      NUMERIC(24, 4) NOT NULL,
    PRIMARY KEY (asset_id, timeframe, timestamp)
) PARTITION BY RANGE (timestamp);

CREATE TABLE forum_scraped_data (
    id               BIGSERIAL PRIMARY KEY,
    asset_id         INT REFERENCES assets(id) ON DELETE CASCADE,
    source           VARCHAR(50) NOT NULL,
    external_id      VARCHAR(120),                -- id na origem → dedupe
    post_timestamp   TIMESTAMPTZ NOT NULL,
    content_text     TEXT NOT NULL,
    language         VARCHAR(5) NOT NULL,         -- 'pt' | 'en' → decide o modelo NLP
    sentiment_score  NUMERIC(4, 3),               -- NULL até ser pontuado
    sentiment_model  VARCHAR(40),                 -- 'finbert-v1' | 'bertimbau-fin-v2'
    engagement_count INT NOT NULL DEFAULT 0,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_post UNIQUE (source, external_id)
);
CREATE INDEX idx_forum_asset_time ON forum_scraped_data(asset_id, post_timestamp DESC);

CREATE TABLE market_alerts (
    id                   BIGSERIAL PRIMARY KEY,
    asset_id             INT NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
    timeframe            VARCHAR(5) NOT NULL,
    timestamp            TIMESTAMPTZ NOT NULL,
    engine_version       VARCHAR(20) NOT NULL,
    is_backtest          BOOLEAN NOT NULL DEFAULT FALSE,

    -- Features (SPEC §2)
    close_price_at_alert NUMERIC(18, 8) NOT NULL,
    regression_slope     NUMERIC(12, 8) NOT NULL, -- sobre LOG-preço
    regression_r2        NUMERIC(5, 4) NOT NULL,  -- separa regime
    deviation_from_mean  NUMERIC(6, 3) NOT NULL,
    volume_z_score       NUMERIC(6, 3) NOT NULL,  -- sobre LOG-volume
    atr                  NUMERIC(18, 8) NOT NULL,
    aggregated_sentiment NUMERIC(4, 3),           -- NULL quando não há dado textual
    market_regime        VARCHAR(15) NOT NULL,    -- 'LATERAL' | 'TENDENCIA' | 'NERVOSO'

    -- Saída (SPEC §3-§4)
    calculated_score     INT NOT NULL,
    alert_type           VARCHAR(10) NOT NULL,    -- 'BUY' | 'SELL'
    trigger_price        NUMERIC(18, 8) NOT NULL,
    take_profit_price    NUMERIC(18, 8) NOT NULL,
    stop_loss_price      NUMERIC(18, 8) NOT NULL,

    -- Triple barrier (SPEC §5)
    outcome              VARCHAR(15),             -- 'TP'|'SL'|'TIMEOUT'| NULL = aberto
    outcome_return       NUMERIC(8, 4),           -- % LÍQUIDO de custos
    max_return_reached   NUMERIC(8, 4),
    closed_at            TIMESTAMPTZ,

    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_alerts_training ON market_alerts(outcome) WHERE outcome IS NOT NULL;
CREATE INDEX idx_alerts_open     ON market_alerts(asset_id) WHERE outcome IS NULL;

CREATE TABLE alert_evidence (
    alert_id BIGINT NOT NULL REFERENCES market_alerts(id) ON DELETE CASCADE,
    post_id  BIGINT NOT NULL REFERENCES forum_scraped_data(id) ON DELETE CASCADE,
    weight   NUMERIC(5, 4) NOT NULL,              -- contribuição no sentimento agregado
    PRIMARY KEY (alert_id, post_id)
);
```

---

## 5. Endpoints (Fase 3)

Auth: token estático único no header (uso próprio — OAuth seria cerimônia sem função).

| Método | Rota | Função |
|---|---|---|
| `GET` | `/api/v1/assets` | Ativos monitorados |
| `POST` | `/api/v1/assets` | Adiciona ticker à watchlist |
| `GET` | `/api/v1/dashboard/watchlist` | Estado estatístico dos ativos (σ, regime, z-score de volume) |
| `GET` | `/api/v1/alerts/active` | Alertas com `outcome IS NULL` + score + TP/SL |
| `GET` | `/api/v1/alerts/{id}/justification` | Features + posts via `alert_evidence` (a tela do "porquê") |
| `GET` | `/api/v1/performance` | Curva de equity real do motor vs. o backtest |

Se as duas curvas de `/performance` divergirem muito, **há lookahead no backtest** — é o canário
mais barato que existe para esse bug.
