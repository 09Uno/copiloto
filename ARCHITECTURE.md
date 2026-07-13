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
┌─────────────┐  HTTP   ┌──────────────┐         ┌──────────┐
│  Frontend   │────────>│   FastAPI    │         │ Telegram │  ← é aqui que o alerta
│ (investiga) │<────────│ (só lê)      │         │  (avisa) │    te encontra
└─────────────┘   SSE   └──────┬───────┘         └────▲─────┘
                               │                      │
                        ┌──────▼───────┐              │
                        │   Supabase   │              │
                        └──────▲───────┘              │
                               │                      │
┌──────────────────────────────┴──────────────────────┴───────────┐
│                            Worker                               │
│                                                                 │
│  stream_crypto   WebSocket Binance, contínuo   → vela fechada   │
│  ingest_eod      APScheduler, no fechamento    → vela diária    │
│  compute_signals vela fechada → engine/ → market_alerts         │
│  close_alerts    alertas abertos → triple barrier → outcome     │
└─────────────────────────────────────────────────────────────────┘
```

A API **não calcula nada** — serve o que o worker já persistiu. O dashboard é ferramenta de
*investigação* (o porquê do alerta, o histórico, a curva de equity), não de vigilância:
ninguém fica olhando para uma tela às 3h da manhã quando o BTC rompe a banda. Quem avisa é o Telegram.

---

## 3. Monitoramento em tempo real

### 3.1 O sinal só existe na vela FECHADA

Regra dura, e a mais importante desta seção. A vela em formação tem OHLC que **ainda vai mudar** —
um sinal calculado sobre ela aparece e some conforme o preço oscila (*repaint*). Fica convincente ao
vivo e é **impossível de reproduzir no backtest**, porque o backtest só vê velas fechadas. Toda
divergência entre o desempenho real e o simulado nasce de furos assim.

Portanto a cadência do motor de sinal é: **a cada 15 minutos** (cripto) e **uma vez por dia** (ações).
Não é tick a tick, e não precisa ser.

### 3.2 Cripto — WebSocket Binance (o único tempo real de verdade)

```
wss://stream.binance.com:9443/stream?streams=btcusdt@kline_15m/ethusdt@kline_15m/solusdt@kline_15m
```

O stream empurra a vela parcial a cada ~1s. O campo que interessa é `k.x`:

```jsonc
{ "data": { "k": {
    "t": 1752300000000,  // open time
    "o": "...", "h": "...", "l": "...", "c": "...", "v": "...",
    "x": false           // ← false = ainda em formação. IGNORAR.
                         //   true  = vela FECHADA. É o único gatilho válido.
}}}
```

Ao receber `x == true`: grava a vela (Parquet + Postgres) → recalcula as features → avalia a regra →
persiste o alerta, se houver → dispara o Telegram. Latência: segundos após o fechamento.

**Reconexão não é opcional.** A Binance derruba a conexão a cada 24h, e queda de rede acontece.
Ao reconectar, o worker **rebusca via REST** o intervalo perdido (o `backfill` incremental já faz
exatamente isso) antes de voltar a confiar no stream. Sem isso, um gap silencioso entra na série e
contamina as janelas dos indicadores.

### 3.3 Ações — agendado, porque tempo real gratuito não existe

Não há fonte gratuita de cotação em tempo real para B3 ou EUA; o `yfinance` entrega com **15 minutos
de atraso**. É exatamente por isso que o SPEC §1 não tem day trade em ação — não é escolha de escopo,
é limitação física do dado. Para swing, isso é irrelevante: um sinal diário não fica melhor por
chegar 15 minutos antes.

| Job | Quando | Fuso |
|---|---|---|
| `ingest_eod` B3 | 18:30 | America/Sao_Paulo |
| `ingest_eod` EUA | 17:00 | America/New_York (o offset UTC muda 2x/ano — **agendar no fuso da bolsa, nunca em UTC fixo**) |

### 3.4 Alertas abertos — o único lugar onde streaming ganha do polling

Dentro de uma vela de 15 minutos, o preço pode tocar o stop e voltar. Quem só olha o `close` não vê,
e registra como vencedora uma operação que **teria sido estopada**. É o mesmo problema de desempate do
triple-barrier (SPEC §5), agora ao vivo.

Por isso `close_alerts` consome o preço contínuo do stream — não o `close` da vela — para decidir se
uma barreira foi tocada. Em ações, sem dado intrabar, o desempate usa o timeframe menor disponível e,
na dúvida, **assume o pior caso (stop primeiro)**. Errar para o lado pessimista mantém o histórico de
treino honesto; errar para o otimista fabrica uma borda que não existe.

### 3.5 Onde isso roda — decisão pendente

Cripto é 24/7, então o worker de streaming precisa estar **ligado 24/7**:

| Opção | Custo | O que se perde |
|---|---|---|
| PC local | R$ 0 | Todo reinício/queda de internet = gap. Inviável a médio prazo. |
| **VPS (Hetzner/DO)** | ~US$ 5/mês | Nada. É o desenho pretendido. |
| Cron a cada 15min via REST | R$ 0 | O streaming; o TP/SL perde a precisão intrabar (§3.4). Aceitável como meio-termo. |

**Decidir só depois da Fase 2.** Seria estranho pagar VPS para monitorar em tempo real uma estratégia
que ainda não sabemos se tem borda. O backtest roda offline, no PC, e é ele que autoriza este gasto.

---

## 4. Layout do repositório

`[x]` = existe;  `[ ]` = previsto.

```
day-and-swing/
├── data/                        # [x] Parquet, fora do git (reprodutível via backfill)
├── infra/schema.sql             # [x] Postgres puro, idempotente
├── backend/
│   ├── .env                     # [x] DATABASE_URL — NUNCA versionado
│   ├── app/
│   │   ├── cli.py               # [x] dands backfill | doctor | show | db
│   │   ├── core/
│   │   │   ├── config.py        # [x] Params, watchlist, Market, Timeframe
│   │   │   ├── params.yaml      # [x] hiperparâmetros (SPEC §7)
│   │   │   └── db.py            # [x] Supabase: init_schema, load_series
│   │   ├── ingest/
│   │   │   ├── store.py         # [x] Parquet + invariantes (UTC, sem dup, ordenado)
│   │   │   ├── binance.py       # [x] klines REST · [ ] WebSocket (§3.2)
│   │   │   ├── yahoo.py         # [x] EOD
│   │   │   └── gaps.py          # [x] detecção de buracos
│   │   ├── engine/              # [ ] Fase 1 — módulo PURO, sem I/O (SPEC §2-§4)
│   │   │   ├── indicators.py    #     regressão log-preço, bandas, z-score, ATR
│   │   │   ├── regime.py        #     LATERAL | TENDENCIA | NERVOSO
│   │   │   ├── signals.py       #     regra + TP/SL + filtro R:R
│   │   │   └── barriers.py      #     triple barrier
│   │   ├── api/                 # [ ] Fase 3
│   │   ├── workers/             # [ ] Fase 3 — stream, eod, signals, close_alerts (§2)
│   │   └── nlp/                 # [ ] Fase 5
│   ├── backtest/                # [ ] Fase 2 — roda offline, importa engine/
│   └── tests/                   # [x] invariantes do store
└── frontend/                    # [ ] Fase 4
```

**`engine/` é puro de propósito:** recebe um DataFrame, devolve features. Sem banco, sem rede.
É o que permite o backtest (Fase 2) e o motor em produção (Fase 3) rodarem **exatamente o mesmo
código** — se forem implementações diferentes, os resultados divergem e o backtest vira ficção.

---

## 5. Schema (DDL)

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

## 6. Endpoints (Fase 3)

Auth: token estático único no header (uso próprio — OAuth seria cerimônia sem função).

| Método | Rota | Função |
|---|---|---|
| `GET` | `/api/v1/assets` | Ativos monitorados |
| `POST` | `/api/v1/assets` | Adiciona ticker à watchlist |
| `GET` | `/api/v1/dashboard/watchlist` | Estado estatístico dos ativos (σ, regime, z-score de volume) |
| `GET` | `/api/v1/alerts/active` | Alertas com `outcome IS NULL` + score + TP/SL |
| `GET` | `/api/v1/alerts/{id}/justification` | Features + posts via `alert_evidence` (a tela do "porquê") |
| `GET` | `/api/v1/performance` | Curva de equity real do motor vs. o backtest |
| `GET` | `/api/v1/stream` | **SSE** — empurra alerta novo e preço para o dashboard aberto |

Se as duas curvas de `/performance` divergirem muito, **há lookahead no backtest** — é o canário
mais barato que existe para esse bug.

**Por que SSE e não WebSocket:** o fluxo é unidirecional (servidor → tela), o SSE reconecta sozinho
e é uma linha de `EventSource` no React. WebSocket aqui só traria a complexidade do handshake sem
usar a via de volta.

O `/stream` é conveniência do dashboard, **não** o canal de alerta — quem avisa é o Telegram (§2).
