# Plano de Desenvolvimento — Motor Quantamental Adaptativo

> **Contexto de uso:** ferramenta de **uso próprio**, single-user, self-hosted.
> Não há multi-tenancy, billing, nem distribuição de recomendações a terceiros.
> Isso elimina a camada de usuários/assinatura do schema e a exposição regulatória (CVM),
> mas **não** elimina a necessidade de validar estatisticamente a estratégia antes de operar com dinheiro real.

Este documento substitui as seções de planejamento operacional de `idea_and_planning.md` e
`architecture_and_tech_stack.md` naquilo que conflitar. A visão de produto e a stack permanecem válidas.

---

## 0. Princípios que guiam a ordem das fases

1. **Backtest antes de produto.** Nenhuma linha de API ou frontend antes de existir evidência,
   em dados históricos e **líquida de custos**, de que a regra tem borda. Se a borda não existe,
   todo o resto é decoração cara.
2. **Regra determinística antes de ML.** A Fase 1 não tem machine learning nenhum. Pesos fixos,
   explicáveis, auditáveis. O ML só entra quando houver milhares de rótulos gerados por backtest —
   e ele terá que **bater o baseline determinístico** para justificar sua existência.
3. **Cada horizonte no mercado onde ele é viável.** Ver matriz abaixo. Forçar day trade em dado
   com atraso de 15 minutos não é ambição, é auto-sabotagem.
4. **Uma fase só começa quando a anterior tem critério de saída atendido.** Cada fase abaixo tem
   um "Definition of Done" explícito.

---

## 1. Matriz Mercado × Horizonte (o que é possível com dado gratuito)

| Mercado | Day Trade (15m) | Swing (diário) | Longo Prazo / Fundamentalista | Opções |
|---|---|---|---|---|
| **Cripto** (Binance) | ✅ WebSocket em tempo real, sem delay, histórico completo | ✅ | ⚠️ sem fundamentos clássicos; usar on-chain/dominância depois | ❌ fora de escopo |
| **Ações EUA** (yfinance) | ❌ delay de 15min inviabiliza reversão intradiária | ✅ EOD confiável | ✅ balanços disponíveis via yfinance | ⚠️ Fase 6 |
| **Ações B3** (brapi.dev / yfinance) | ❌ mesmo motivo + cobertura intraday ruim | ✅ EOD | ✅ | ⚠️ Fase 6 (grade de opções é o dado mais difícil de obter grátis) |

**Consequência prática:** o motor é **um só**, com os mesmos indicadores e a mesma lógica de risco.
O que muda por mercado é apenas o *conector de ingestão* e o *timeframe habilitado*. Nada de escrever
três sistemas.

**Sobre `yfinance`:** aceitável para EOD em uso próprio (é o caso aqui). Não tem SLA e quebra sem aviso —
o ingestor precisa tratar falha como normal, não como exceção. Para B3, avaliar `brapi.dev` como
fonte primária de EOD e usar `yfinance` como fallback.

---

## 2. Correções de matemática incorporadas (vs. documentos originais)

Estas mudanças são pré-requisito de todas as fases. Sem elas, o backtest mede a coisa errada.

| # | Problema no doc original | Correção adotada |
|---|---|---|
| 1 | Compra em −2σ, alvo em μ, stop em −3.2σ → R:R de **1.67:1**, abaixo do filtro 1:2 que o próprio doc exige. As regras se anulam. | Alvo e stop deixam de ser níveis fixos. Calcula-se `SL = entrada − 1.5×ATR` e `TP = μ (linha de regressão)`. O filtro `TP_dist ≥ 2 × SL_dist` vira **critério de descarte**, não uma promessa. Sinais que não passam são simplesmente ignorados. |
| 2 | Regressão sobre preço bruto | Regressão sobre **log-preço**. O slope passa a ser comparável entre PETR4 e BTC e estável no tempo. Feature final: `slope_normalizado` (retorno log por período). |
| 3 | "±2σ contém 95% do tempo" | Falso para retornos financeiros (caudas gordas). A banda continua sendo usada como heurística de exaustão, mas **os limiares serão calibrados empiricamente no backtest**, não assumidos da normal. |
| 4 | Reversão à média aplicada em qualquer regime | **Filtro de regime obrigatório.** Só opera reversão quando o R² da regressão for baixo (mercado lateral). Em tendência forte (R² alto + \|slope\| alto), a banda é sinal de *continuação*, não de reversão — e o sistema não opera contra ela. |
| 5 | Z-score cru sobre volume | Z-score sobre **log(volume)** (distribuição de volume é lognormal-ish; o z-score cru é mal-comportado). |
| 6 | Custos ignorados | Toda métrica de backtest é **líquida** de taxa de corretagem, spread estimado e slippage. Uma estratégia lucrativa só antes de custos é uma estratégia que perde dinheiro. |
| 7 | Rótulo `was_profitable` ambíguo | **Triple-barrier method** (López de Prado): alvo, stop e **horizonte máximo de tempo**. Se o preço toca alvo e stop na mesma vela, desempata com dados de timeframe menor. Se nenhum é atingido no horizonte, o rótulo é o retorno na expiração (não é NULL). |
| 8 | Hiperparâmetros nunca definidos ("últimos N períodos") | Todos parametrizados e versionados em config (ver §3). Valores iniciais definidos; a calibração é *output* do backtest, não input. |
| 9 | "IA muda os pesos para 10/90 ou 20/80" | Isso não é como um XGBoost funciona. Fase 1 = regra determinística com **flag de regime** (explicável de graça). Fase 5 = modelo real, com SHAP para explicabilidade. Os dois não coexistem. |

---

## 3. Hiperparâmetros iniciais (a serem calibrados na Fase 2)

```yaml
regressao:
  janela: 100          # períodos (velas)
  base: log_preco
bandas:
  janela_media: 20
  n_sigma_entrada: 2.0
regime:
  r2_max_lateral: 0.30 # acima disso, considera-se tendência → não opera reversão
volume:
  janela_zscore: 50
  z_minimo: 2.0
  base: log_volume
risco:
  atr_janela: 14
  stop_atr_mult: 1.5
  rr_minimo: 2.0       # descarta o sinal se TP_dist < 2 × SL_dist
  horizonte_max:       # barreira temporal do triple-barrier
    15m: 24            # velas (~6h)
    1d: 10             # dias
custos:
  cripto_taker_pct: 0.10
  acoes_br_pct: 0.05
  slippage_pct: 0.05
```

---

## 4. Schema revisado (DDL)

Mudanças em relação ao `architecture_and_tech_stack.md`:

- **`TIMESTAMPTZ` em tudo, gravado em UTC.** B3 + EUA + cripto = três fusos e horário de verão americano
  mudando o offset duas vezes por ano. Este é o bug que só aparece em novembro e corrompe meses de série.
- **Sem tabela `users` / `watchlists` / billing** — uso próprio, single-user. A watchlist é um simples
  booleano/enum em `assets`.
- **`UNIQUE (ticker, market_type)`** em vez de `ticker` global (o mesmo ticker pode existir em mercados diferentes).
  `VARCHAR(20)` para caber opções da B3.
- **Chave natural em `asset_prices`** — `(asset_id, timeframe, timestamp)` já é a PK; o `BIGSERIAL` era desperdício.
- **`model_version` em todo score gerado** — sem isso, retreinar o modelo de sentimento invalida
  silenciosamente todo o histórico e o dataset de treino vira uma mistura inútil de gerações.
- **`alert_evidence`** — liga o alerta aos posts que o motivaram. Sem essa tabela, a promessa central
  do produto (explicabilidade) é literalmente não implementável.
- **Particionamento por tempo** em `asset_prices` desde o início (ou TimescaleDB). Migrar depois dói.

```sql
CREATE TABLE assets (
    id            SERIAL PRIMARY KEY,
    ticker        VARCHAR(20) NOT NULL,
    market_type   VARCHAR(20) NOT NULL,          -- 'B3' | 'US' | 'CRYPTO'
    name          VARCHAR(120) NOT NULL,
    is_watchlist  BOOLEAN NOT NULL DEFAULT FALSE,
    timeframes    TEXT[] NOT NULL DEFAULT '{1d}',-- timeframes habilitados p/ este ativo
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_asset UNIQUE (ticker, market_type)
);

CREATE TABLE asset_prices (
    asset_id    INT NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
    timeframe   VARCHAR(5) NOT NULL,             -- '15m' | '1d'
    timestamp   TIMESTAMPTZ NOT NULL,            -- SEMPRE UTC
    open_price  NUMERIC(18, 8) NOT NULL,
    high_price  NUMERIC(18, 8) NOT NULL,
    low_price   NUMERIC(18, 8) NOT NULL,
    close_price NUMERIC(18, 8) NOT NULL,
    volume      NUMERIC(24, 4) NOT NULL,
    PRIMARY KEY (asset_id, timeframe, timestamp)
) PARTITION BY RANGE (timestamp);
-- criar partições anuais; ou trocar por TimescaleDB hypertable

CREATE TABLE forum_scraped_data (
    id               BIGSERIAL PRIMARY KEY,
    asset_id         INT REFERENCES assets(id) ON DELETE CASCADE,
    source           VARCHAR(50) NOT NULL,
    external_id      VARCHAR(120),               -- id do post na origem (dedupe)
    post_timestamp   TIMESTAMPTZ NOT NULL,
    content_text     TEXT NOT NULL,
    language         VARCHAR(5) NOT NULL,        -- 'pt' | 'en' — decide qual modelo NLP usar
    sentiment_score  NUMERIC(4, 3),              -- NULL até ser pontuado
    sentiment_model  VARCHAR(40),                -- ex: 'finbert-v1', 'bertimbau-fin-v2'
    engagement_count INT NOT NULL DEFAULT 0,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_post UNIQUE (source, external_id)
);
CREATE INDEX idx_forum_asset_time ON forum_scraped_data(asset_id, post_timestamp DESC);

CREATE TABLE market_alerts (
    id                  BIGSERIAL PRIMARY KEY,
    asset_id            INT NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
    timeframe           VARCHAR(5) NOT NULL,
    timestamp           TIMESTAMPTZ NOT NULL,
    engine_version      VARCHAR(20) NOT NULL,    -- versão da regra/modelo que gerou o sinal
    is_backtest         BOOLEAN NOT NULL DEFAULT FALSE,

    -- Features (estado do mercado no momento do sinal)
    close_price_at_alert NUMERIC(18, 8) NOT NULL,
    regression_slope     NUMERIC(12, 8) NOT NULL,  -- sobre LOG-preço, normalizado
    regression_r2        NUMERIC(5, 4) NOT NULL,   -- detecta regime lateral vs. tendência
    deviation_from_mean  NUMERIC(6, 3) NOT NULL,   -- em desvios padrão
    volume_z_score       NUMERIC(6, 3) NOT NULL,   -- sobre LOG-volume
    atr                  NUMERIC(18, 8) NOT NULL,
    aggregated_sentiment NUMERIC(4, 3),            -- NULL quando não há dado textual
    market_regime        VARCHAR(15) NOT NULL,     -- 'LATERAL' | 'TENDENCIA' | 'NERVOSO'

    -- Saída
    calculated_score  INT NOT NULL,
    alert_type        VARCHAR(10) NOT NULL,
    trigger_price     NUMERIC(18, 8) NOT NULL,
    take_profit_price NUMERIC(18, 8) NOT NULL,
    stop_loss_price   NUMERIC(18, 8) NOT NULL,

    -- Triple-barrier (desfecho)
    outcome           VARCHAR(15),   -- 'TP' | 'SL' | 'TIMEOUT' | NULL (ainda aberto)
    outcome_return    NUMERIC(8, 4), -- retorno % LÍQUIDO de custos
    max_return_reached NUMERIC(8, 4),
    closed_at         TIMESTAMPTZ,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_alerts_training ON market_alerts(outcome) WHERE outcome IS NOT NULL;
CREATE INDEX idx_alerts_open ON market_alerts(asset_id) WHERE outcome IS NULL;

-- Liga o alerta às evidências textuais que o justificaram (endpoint /justification)
CREATE TABLE alert_evidence (
    alert_id BIGINT NOT NULL REFERENCES market_alerts(id) ON DELETE CASCADE,
    post_id  BIGINT NOT NULL REFERENCES forum_scraped_data(id) ON DELETE CASCADE,
    weight   NUMERIC(5, 4) NOT NULL,  -- contribuição do post no sentimento agregado
    PRIMARY KEY (alert_id, post_id)
);
```

---

## 5. Fases de desenvolvimento

### Fase 0 — Fundação e Ingestão Histórica
Sem isso, não há backtest.

- Repositório, `docker-compose` (Postgres + pgAdmin), migrações (Alembic).
- Schema acima aplicado.
- **Ingestor Binance**: histórico completo de klines (15m e 1d) dos pares da watchlist. É o dataset mais
  limpo e mais longo que existe de graça — será a base de validação da estratégia.
- **Ingestor EOD** (yfinance / brapi): histórico diário de ações B3 e EUA.
- Tratamento de falha como caso normal (retry, gap detection, backfill idempotente).

**Done quando:** houver ≥ 2 anos de histórico de 15m para os pares cripto e ≥ 5 anos de diário
para as ações, com detecção de gaps passando limpa.

---

### Fase 1 — Motor de Indicadores (biblioteca pura, sem I/O)
Um módulo Python testável, que recebe um DataFrame de OHLCV e devolve as features.

- Regressão linear sobre log-preço → `slope`, `r2`.
- Bandas de desvio padrão → `deviation_from_mean`.
- Z-score de log-volume, ATR.
- Classificador de regime (`LATERAL` / `TENDENCIA` / `NERVOSO`).
- Regra de sinal determinística + cálculo de TP/SL + filtro de R:R mínimo.

**Done quando:** cobertura de testes sobre séries sintéticas de comportamento conhecido
(tendência pura, lateral pura, choque de volatilidade) — e o motor não emitir sinal de reversão
em tendência forte.

---

### Fase 2 — Backtest (a fase que decide se o projeto continua)
A mais importante do plano. Roda **offline**, sem API, sem frontend.

- Walk-forward sobre o histórico, aplicando o motor da Fase 1 vela a vela (**sem lookahead**:
  só usa dados disponíveis até `t`).
- Rotulagem via triple-barrier, com desempate intrabar quando alvo e stop caem na mesma vela.
- Métricas **líquidas de custos**: expectância por trade, taxa de acerto, profit factor,
  drawdown máximo, Sharpe — **sempre comparadas contra buy & hold no mesmo período**.
- Grid search dos hiperparâmetros do §3, com validação out-of-sample (treina em 2022–2023,
  valida em 2024–2025). Overfitar o grid no in-sample é o modo mais fácil de se enganar.

**Done quando:** existir **pelo menos uma combinação mercado × timeframe** com expectância
positiva líquida de custos **fora da amostra**. Se nenhuma existir, o projeto para aqui e a
regra é repensada — não se constrói o SaaS por cima de uma borda que não existe.

---

### Fase 3 — Motor em Produção + API
Só depois que a Fase 2 der sinal verde.

- FastAPI + SQLAlchemy async. Auth = um único token estático (uso próprio; não precisa de OAuth).
- Scheduler: **APScheduler dentro do próprio processo worker** para começar. O n8n do documento
  original não elimina a necessidade de execução assíncrona — ele apenas chama um endpoint que,
  do jeito descrito, processaria o lote inteiro na request e estouraria timeout. Se o n8n entrar
  depois, o endpoint precisa **enfileirar e retornar `202`**.
- Worker de ingestão contínua (WS Binance para cripto; EOD agendado para ações).
- Worker de avaliação de desfecho: fecha os alertas abertos (`outcome IS NULL`) aplicando as barreiras.
- Endpoints: `/assets`, `/dashboard/watchlist`, `/alerts/active`, `/alerts/{id}/justification`.

**Done quando:** o sistema gerar e fechar alertas sozinho por uma semana, e as métricas
observadas em produção baterem com as do backtest (se divergirem muito, há lookahead no backtest).

---

### Fase 4 — Dashboard (Vite + React + Tailwind)
- Watchlist com o estado estatístico de cada ativo (distância da média em σ, regime, z-score de volume).
- Painel de alertas ativos com TP/SL e o **porquê** (a tela de justificativa consumindo `alert_evidence`).
- Gráfico com bandas, linha de regressão e marcações de entrada/saída.
- Histórico de desempenho: a curva de equity real do motor, lado a lado com o backtest.

---

### Fase 5 — Sentimento (NLP)
Deliberadamente **depois** do motor funcionar. O sinal quantitativo precisa ter borda sozinho antes
de você tentar melhorá-lo com texto — caso contrário você não consegue medir se o texto ajudou.

- Coletores: Reddit (PRAW, com credencial), feeds RSS.
  **Não raspar ADVFN/fóruns B3** — viola os termos de uso e cai em Cloudflare na primeira semana.
- Modelo por idioma: FinBERT (inglês) / BERTimbau-financeiro ou similar (português).
  *FinBERT é treinado em inglês — usá-lo em texto PT-BR produz ruído com aparência de sinal.*
- Agregação ponderada por engajamento e recência → `aggregated_sentiment` + `alert_evidence`.
- **Medir se o sentimento melhora a expectância no backtest.** Se não melhorar, ele não entra na regra.

---

### Fase 6 — Machine Learning (só com dados suficientes)
- Dataset de treino = **rótulos do backtest** (todas as janelas), não apenas os alertas que o sistema
  disparou. Treinar só nos próprios disparos gera viés de seleção: você nunca observa o desfecho dos
  sinais que *não* emitiu, então o modelo não aprende a discriminar — apenas descreve o que a regra já escolhia.
- Modelo: gradient boosting sobre as features de `market_alerts`, com validação temporal
  (nunca k-fold aleatório em série temporal).
- Explicabilidade via SHAP, alimentando a tela de justificativa.
- **Critério de adoção:** o modelo só substitui a regra determinística se bater o baseline dela
  fora da amostra. Caso contrário, fica desligado.

---

### Fase 7 — Longo Prazo, Fundamentalista e Opções
Esta é a fatia mais valiosa para você (avaliar compra de longo prazo), e é também a **mais independente**
do resto — ela pode ser desenvolvida em paralelo à Fase 4 se você quiser, porque não depende do motor
de reversão à média.

- **Fundamentalista:** balanços trimestrais via `yfinance` (`.financials`, `.balance_sheet`).
  Modelos clássicos: Graham, Gordon, múltiplos históricos (P/L, EV/EBITDA) comparados contra a
  própria mediana histórica do ativo e contra o setor. Sem ML — é aritmética contábil.
- **Opções:** deixar por último. A grade de opções da B3 é o dado mais difícil de obter de graça;
  sem ela, monitoramento de volatilidade implícita não sai do papel. Reavaliar viabilidade da fonte
  antes de investir tempo aqui.

---

## 6. Ordem sugerida de execução

```
Fase 0 (fundação + histórico)
   └─> Fase 1 (indicadores)
          └─> Fase 2 (BACKTEST) ◄── portão de decisão: continua ou repensa
                 ├─> Fase 3 (motor em produção + API)
                 │      └─> Fase 4 (dashboard)
                 │             └─> Fase 5 (sentimento) ─> Fase 6 (ML)
                 └─> Fase 7 (fundamentalista/longo prazo) — paralelizável
```

**O portão da Fase 2 é inegociável.** É o único momento barato de descobrir que a estratégia não
funciona. Depois dele, cada semana investida é uma semana apostada numa premissa não testada.

---

## 7. Correção pendente nos documentos existentes

As fórmulas em `idea_and_planning.md` estão **literalmente corrompidas**: o script Python que gerou
o arquivo não usou string *raw*, então o LaTeX perdeu as barras invertidas — `\alpha` virou `lpha`,
`\beta` virou `eta`, `\frac` virou `rac`, `\text` virou TAB + `ext`. Afeta as linhas 49, 59, 68, 70,
84 e 97. Corrigir junto com a incorporação das mudanças de matemática do §2 deste plano.
