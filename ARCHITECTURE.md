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
| Banco | **Supabase** (Postgres 17 + `pgvector`) | Camada de **serviço**: API e dashboard leem dele. |
| Dado bruto | **Parquet** local (`data/`) | Camada de **aterrissagem**: imutável, reprodutível. |
| Alertas | **Telegram** (bot) | O canal que te encontra. O dashboard não vigia; ele investiga. |

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

## 5. Schema

**Fonte única: [infra/schema.sql](infra/schema.sql)** — Postgres puro, idempotente, aplicado por
`dands db init`. Este documento não duplica o DDL: uma segunda cópia diverge da primeira no dia em
que alguém esquece de atualizá-la, e aí ninguém sabe qual é a verdadeira.

Aqui ficam as **decisões** e o porquê de cada uma.

| Tabela | Papel |
|---|---|
| `assets` | Universo monitorado. `currency` roteia o trade para a banca certa. |
| `asset_prices` | OHLCV. Espelho do Parquet, para a API ler. |
| `market_alerts` | O que o motor **sugeriu** + features + desfecho da barreira tripla. |
| `alert_evidence` | Liga o alerta aos posts que o motivaram (a tela do "porquê"). |
| `forum_scraped_data` | Texto minerado + sentimento (Fase 5). |
| `accounts` | A banca — **uma por moeda** (SPEC §8.1). |
| `trades` | O que **executou** de verdade. A diferença vs. `market_alerts` é o slippage. |
| `equity_snapshots` | Fecho diário → ganho no período e **drawdown real**. |
| `fx_rates` | USDBRL, só para a visão consolidada. |

### As decisões que não são óbvias

**`TIMESTAMPTZ` em tudo, gravado em UTC.** B3 + EUA + cripto são três fusos, e o horário de verão
americano move o offset duas vezes por ano. `TIMESTAMP` sem fuso é o bug que só aparece em novembro
e corrompe meses de série.

**Chave natural em `asset_prices`** — `(asset_id, timeframe, timestamp)` já é a PK. O `BIGSERIAL`
do rascunho original era um índice a mais sem função nenhuma.

**`UNIQUE (ticker, market_type)`**, não `ticker` global: o mesmo ticker pode existir em mercados
diferentes. `VARCHAR(20)` para caber opções da B3.

**`engine_version` / `sentiment_model` em todo score gerado.** Sem isso, retreinar o modelo invalida
o histórico **em silêncio**: o dataset de treino vira uma mistura de gerações incomparáveis, e nada
no banco denuncia isso.

**`UNIQUE (alert_id)` em `trades`** — clicar "Confirmar" duas vezes não duplica a posição.

**Barreiras (`take_profit`, `stop_loss`) são níveis do MERCADO.** Não se movem porque seu
preenchimento foi pior; o que piora é o `rr_real`, recalculado no fill (SPEC §8.3).

**Sem TimescaleDB e sem particionamento.** O Supabase não oferece a extensão, e particionar ~300k
linhas numa ferramenta de uso próprio é otimização prematura. Um índice **BRIN** em `timestamp`
— feito exatamente para dado inserido em ordem cronológica — dá o ganho a custo quase zero.

**`state_vector vector(5)` + HNSW** (pgvector). As 5 features são **adimensionais por construção**:
se fosse preciso *ajustar* um normalizador sobre o histórico para montar o vetor, o próprio
normalizador veria o futuro. O kNN só pode olhar vizinhos **estritamente anteriores** (SPEC §9).

---

## 6. Endpoints (Fase 3)

Auth: token estático único no header (uso próprio — OAuth seria cerimônia sem função).

| Método | Rota | Função |
|---|---|---|
| `GET` | `/api/v1/assets` | Ativos monitorados |
| `POST` | `/api/v1/assets` | Adiciona ticker à watchlist |
| `GET` | `/api/v1/dashboard/watchlist` | Estado estatístico dos ativos (σ, regime, z-score de volume) |
| `GET` | `/api/v1/alerts/active` | Alertas abertos + score + TP/SL + **qty sugerida** (sizing) |
| `GET` | `/api/v1/alerts/{id}/justification` | Features, posts (`alert_evidence`) e a **analogia histórica** (kNN, SPEC §9) |
| `GET` | `/api/v1/stream` | **SSE** — empurra alerta novo e preço para o dashboard aberto |

**Carteira (SPEC §8)**

| Método | Rota | Função |
|---|---|---|
| `GET` | `/api/v1/accounts` | Bancas (BRL / USD) + caixa + risco por operação |
| `POST` | `/api/v1/alerts/{id}/confirm` | **O botão Confirmar.** Recebe o preenchimento *real* (preço, qty) → cria o `trade`, recalcula o `rr_real` e **avisa se caiu abaixo do mínimo** (§8.3). Idempotente por `UNIQUE (alert_id)`. |
| `POST` | `/api/v1/trades/{id}/close` | Encerra a posição (preço e motivo de saída reais) |
| `GET` | `/api/v1/trades` | Operações, abertas e fechadas |
| `GET` | `/api/v1/portfolio` | Ganho hoje / semana / mês / ano, em % e valor, por banca e consolidado |
| `GET` | `/api/v1/performance` | Curva de equity **real** vs. a do backtest + drawdown |

Se as duas curvas de `/performance` divergirem muito, **há lookahead no backtest** — é o canário
mais barato que existe para esse bug.

**Por que SSE e não WebSocket:** o fluxo é unidirecional (servidor → tela), o SSE reconecta sozinho
e é uma linha de `EventSource` no React. WebSocket aqui só traria a complexidade do handshake sem
usar a via de volta.

O `/stream` é conveniência do dashboard, **não** o canal de alerta — quem avisa é o Telegram (§2).
