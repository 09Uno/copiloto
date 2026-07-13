-- Schema — Postgres puro (roda no Supabase; ver ARCHITECTURE.md §5).
-- Idempotente: pode ser reaplicado (`dands db init`).
--
-- Decisões que divergem do rascunho original:
--   TIMESTAMPTZ em tudo — B3 + EUA + cripto são 3 fusos, e o horário de verão americano
--     move o offset 2x por ano. TIMESTAMP sem fuso é o bug que só aparece em novembro.
--   chave natural em asset_prices — o BIGSERIAL era um índice a mais sem função.
--   engine_version / sentiment_model em todo score — sem isso, retreinar invalida o histórico
--     em silêncio e o dataset de treino vira mistura inútil de gerações.
--   alert_evidence — sem ela, a tela de justificativa é literalmente impossível.
--
-- Sem TimescaleDB (indisponível no Supabase) e sem particionamento: para uso próprio,
-- particionar 300k linhas é otimização prematura. BRIN em timestamp — que é feito
-- exatamente para dado inserido em ordem cronológica — dá o ganho a custo quase zero.
-- Se o volume um dia justificar, particiona-se depois.

CREATE TABLE IF NOT EXISTS assets (
    id           SERIAL PRIMARY KEY,
    ticker       VARCHAR(20)  NOT NULL,
    market_type  VARCHAR(20)  NOT NULL,            -- 'B3' | 'US' | 'CRYPTO'
    name         VARCHAR(120) NOT NULL,
    is_watchlist BOOLEAN      NOT NULL DEFAULT FALSE,
    timeframes   TEXT[]       NOT NULL DEFAULT '{1d}',
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_asset UNIQUE (ticker, market_type)
);

CREATE TABLE IF NOT EXISTS asset_prices (
    asset_id    INT            NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
    timeframe   VARCHAR(5)     NOT NULL,           -- '15m' | '1d'
    timestamp   TIMESTAMPTZ    NOT NULL,           -- SEMPRE UTC
    open_price  NUMERIC(18, 8) NOT NULL,
    high_price  NUMERIC(18, 8) NOT NULL,
    low_price   NUMERIC(18, 8) NOT NULL,
    close_price NUMERIC(18, 8) NOT NULL,
    volume      NUMERIC(24, 4) NOT NULL,
    PRIMARY KEY (asset_id, timeframe, timestamp)
);
CREATE INDEX IF NOT EXISTS idx_prices_ts_brin ON asset_prices USING BRIN (timestamp);

CREATE TABLE IF NOT EXISTS forum_scraped_data (
    id               BIGSERIAL PRIMARY KEY,
    asset_id         INT REFERENCES assets(id) ON DELETE CASCADE,
    source           VARCHAR(50)  NOT NULL,
    external_id      VARCHAR(120),                 -- id na origem → dedupe
    post_timestamp   TIMESTAMPTZ  NOT NULL,
    content_text     TEXT         NOT NULL,
    language         VARCHAR(5)   NOT NULL,        -- 'pt' | 'en' → decide o modelo NLP
    sentiment_score  NUMERIC(4, 3),                -- NULL até ser pontuado
    sentiment_model  VARCHAR(40),                  -- 'finbert-v1' | 'bertimbau-fin-v2'
    engagement_count INT          NOT NULL DEFAULT 0,
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_post UNIQUE (source, external_id)
);
CREATE INDEX IF NOT EXISTS idx_forum_asset_time
    ON forum_scraped_data(asset_id, post_timestamp DESC);

CREATE TABLE IF NOT EXISTS market_alerts (
    id                   BIGSERIAL PRIMARY KEY,
    asset_id             INT         NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
    timeframe            VARCHAR(5)  NOT NULL,
    timestamp            TIMESTAMPTZ NOT NULL,
    engine_version       VARCHAR(20) NOT NULL,
    is_backtest          BOOLEAN     NOT NULL DEFAULT FALSE,

    -- Qual estratégia gerou este alerta. SEM isto, os datasets das três se misturam e o ML
    -- da Fase 6 treinaria em maçãs com laranjas — 'esta ação vai repicar em 10 pregões' e
    -- 'esta ação está barata para carregar 3 anos' não são a mesma pergunta.
    strategy             VARCHAR(15) NOT NULL DEFAULT 'MEAN_REV',
    -- 'MEAN_REV' | 'XSECT' | 'VALUE'

    -- Features (SPEC §2)
    close_price_at_alert NUMERIC(18, 8) NOT NULL,
    regression_slope     NUMERIC(12, 8) NOT NULL,  -- sobre LOG-preço
    regression_r2        NUMERIC(5, 4)  NOT NULL,  -- separa LATERAL de TENDENCIA
    deviation_from_mean  NUMERIC(6, 3)  NOT NULL,
    volume_z_score       NUMERIC(6, 3)  NOT NULL,  -- sobre LOG-volume
    atr                  NUMERIC(18, 8) NOT NULL,
    aggregated_sentiment NUMERIC(4, 3),            -- NULL quando não há dado textual
    market_regime        VARCHAR(15)    NOT NULL,  -- 'LATERAL' | 'TENDENCIA' | 'NERVOSO'

    -- Saída (SPEC §3-§4)
    calculated_score     INT            NOT NULL,
    alert_type           VARCHAR(10)    NOT NULL,  -- 'BUY' | 'SELL'
    trigger_price        NUMERIC(18, 8) NOT NULL,
    take_profit_price    NUMERIC(18, 8) NOT NULL,
    stop_loss_price      NUMERIC(18, 8) NOT NULL,

    -- Triple barrier (SPEC §5)
    outcome              VARCHAR(15),              -- 'TP'|'SL'|'TIMEOUT'| NULL = aberto
    outcome_return       NUMERIC(8, 4),            -- % LÍQUIDO de custos
    max_return_reached   NUMERIC(8, 4),
    closed_at            TIMESTAMPTZ,

    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_alert
        UNIQUE (asset_id, timeframe, timestamp, engine_version, strategy, is_backtest)
);
ALTER TABLE market_alerts ADD COLUMN IF NOT EXISTS strategy VARCHAR(15) NOT NULL
    DEFAULT 'MEAN_REV';
CREATE INDEX IF NOT EXISTS idx_alerts_training
    ON market_alerts(strategy, outcome) WHERE outcome IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_alerts_open
    ON market_alerts(asset_id) WHERE outcome IS NULL;

CREATE TABLE IF NOT EXISTS alert_evidence (
    alert_id BIGINT NOT NULL REFERENCES market_alerts(id) ON DELETE CASCADE,
    post_id  BIGINT NOT NULL REFERENCES forum_scraped_data(id) ON DELETE CASCADE,
    weight   NUMERIC(5, 4) NOT NULL,               -- contribuição no sentimento agregado
    PRIMARY KEY (alert_id, post_id)
);

-- ============================================================================
-- CARTEIRA E EXECUÇÃO (SPEC §8)
-- ============================================================================

-- Uma banca POR MOEDA. Somar tudo num número só esconde a pergunta que importa:
-- um "+3% na semana" pode ser puro dólar subindo, sem nenhuma operação ter dado certo.
CREATE TABLE IF NOT EXISTS accounts (
    id                 SERIAL PRIMARY KEY,
    name               VARCHAR(60)   NOT NULL,
    currency           CHAR(3)       NOT NULL UNIQUE,  -- 'BRL' | 'USD' (USDT conta como USD)
    initial_balance    NUMERIC(18, 2) NOT NULL,
    cash_balance       NUMERIC(18, 2) NOT NULL,
    risk_per_trade_pct NUMERIC(5, 3) NOT NULL DEFAULT 1.0,  -- sizing (SPEC §8.2)
    created_at         TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

ALTER TABLE assets ADD COLUMN IF NOT EXISTS currency CHAR(3) NOT NULL DEFAULT 'USD';
-- B3 → BRL;  US e CRYPTO → USD. É o que roteia o trade para a conta certa.

-- Câmbio só para a VISÃO consolidada — nunca para converter o P&L de um trade,
-- senão o resultado de uma operação em dólar muda sozinho quando o câmbio mexe.
CREATE TABLE IF NOT EXISTS fx_rates (
    date DATE          NOT NULL,
    pair VARCHAR(7)    NOT NULL,                   -- 'USDBRL' (yfinance: BRL=X)
    rate NUMERIC(12, 6) NOT NULL,
    PRIMARY KEY (date, pair)
);

-- O que o motor SUGERIU vive em market_alerts. Aqui fica o que EXECUTOU.
-- A diferença entre os dois é que carrega a informação (slippage → custos do backtest).
CREATE TABLE IF NOT EXISTS trades (
    id         BIGSERIAL PRIMARY KEY,
    account_id INT    NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    asset_id   INT    NOT NULL REFERENCES assets(id)   ON DELETE CASCADE,
    alert_id   BIGINT REFERENCES market_alerts(id),    -- NULL = trade manual, sem alerta
    side       VARCHAR(4)  NOT NULL,                   -- 'BUY' | 'SELL'
    status     VARCHAR(10) NOT NULL DEFAULT 'OPEN',    -- 'OPEN' | 'CLOSED'

    -- Preenchimento real (a verdade)
    entry_price NUMERIC(18, 8) NOT NULL,
    entry_qty   NUMERIC(24, 8) NOT NULL,
    entry_at    TIMESTAMPTZ    NOT NULL,
    entry_fee   NUMERIC(18, 8) NOT NULL DEFAULT 0,

    -- Barreiras: são NÍVEIS DO MERCADO (ATR / linha de regressão). NÃO se movem porque
    -- seu preenchimento foi pior — o mercado não mudou por você ter pagado mais caro.
    -- O que piora é o SEU risco-retorno, e é por isso que rr_real é recalculado no fill:
    -- se cair abaixo de risco.rr_minimo, o sistema avisa (SPEC §8.3).
    take_profit NUMERIC(18, 8) NOT NULL,
    stop_loss   NUMERIC(18, 8) NOT NULL,
    rr_real     NUMERIC(6, 3)  NOT NULL,

    exit_price       NUMERIC(18, 8),
    exit_qty         NUMERIC(24, 8),
    exit_at          TIMESTAMPTZ,
    exit_fee         NUMERIC(18, 8) DEFAULT 0,
    exit_reason      VARCHAR(10),                  -- 'TP'|'SL'|'MANUAL'|'TIMEOUT'
    realized_pnl     NUMERIC(18, 2),               -- na moeda da conta
    realized_pnl_pct NUMERIC(8, 4),

    notes      TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Um alerta só vira UMA operação: clicar "Confirmar" duas vezes não duplica a posição.
    CONSTRAINT uq_trade_alert UNIQUE (alert_id)
);
CREATE INDEX IF NOT EXISTS idx_trades_open ON trades(account_id) WHERE status = 'OPEN';
CREATE INDEX IF NOT EXISTS idx_trades_closed_at ON trades(account_id, exit_at DESC)
    WHERE status = 'CLOSED';

-- Fecho diário da banca: é daqui que saem "ganho hoje/semana/mês" e o DRAWDOWN REAL —
-- o número que de fato importa e que quase ninguém olha.
CREATE TABLE IF NOT EXISTS equity_snapshots (
    account_id       INT  NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    date             DATE NOT NULL,
    cash             NUMERIC(18, 2) NOT NULL,
    positions_value  NUMERIC(18, 2) NOT NULL,      -- posições abertas a preço de mercado
    equity           NUMERIC(18, 2) NOT NULL,      -- cash + positions_value
    realized_pnl_day NUMERIC(18, 2) NOT NULL,
    unrealized_pnl   NUMERIC(18, 2) NOT NULL,
    PRIMARY KEY (account_id, date)
);

-- ============================================================================
-- ANALOGIA HISTÓRICA (SPEC §9)
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS vector;

-- [slope_norm, r2, deviation_from_mean, volume_z_score, atr/close]
-- As 5 features são ADIMENSIONAIS por construção. Isso é de propósito: se fosse preciso
-- AJUSTAR um normalizador sobre o histórico inteiro, o próprio normalizador veria o futuro
-- — vazamento sutil e clássico.
ALTER TABLE market_alerts ADD COLUMN IF NOT EXISTS state_vector vector(5);

CREATE INDEX IF NOT EXISTS idx_alerts_state_vector
    ON market_alerts USING hnsw (state_vector vector_l2_ops);

-- ATENÇÃO ao consultar: a busca por vizinhos SÓ pode olhar alertas estritamente ANTERIORES
--   ... WHERE timestamp < :agora AND outcome IS NOT NULL ORDER BY state_vector <-> :v LIMIT k
-- Um kNN ingênuo sobre a tabela inteira enxerga o futuro e devolve uma taxa de acerto
-- fantástica e falsa.
