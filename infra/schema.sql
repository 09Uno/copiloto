-- Schema do Postgres — ver ARCHITECTURE.md §4 para o porquê de cada decisão.
-- Aplicado automaticamente no primeiro `docker compose up`.
--
-- Resumo das decisões que divergem do rascunho original:
--   TIMESTAMPTZ em tudo (B3 + EUA + cripto = 3 fusos + horário de verão americano);
--   chave natural em asset_prices (o BIGSERIAL era um índice a mais sem função);
--   engine_version / sentiment_model em todo score (senão o retreino invalida o histórico);
--   alert_evidence (sem ela, a tela de justificativa é impossível).

CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE TABLE assets (
    id           SERIAL PRIMARY KEY,
    ticker       VARCHAR(20)  NOT NULL,
    market_type  VARCHAR(20)  NOT NULL,            -- 'B3' | 'US' | 'CRYPTO'
    name         VARCHAR(120) NOT NULL,
    is_watchlist BOOLEAN      NOT NULL DEFAULT FALSE,
    timeframes   TEXT[]       NOT NULL DEFAULT '{1d}',
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_asset UNIQUE (ticker, market_type)
);

CREATE TABLE asset_prices (
    asset_id    INT         NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
    timeframe   VARCHAR(5)  NOT NULL,              -- '15m' | '1d'
    timestamp   TIMESTAMPTZ NOT NULL,              -- SEMPRE UTC
    open_price  NUMERIC(18, 8) NOT NULL,
    high_price  NUMERIC(18, 8) NOT NULL,
    low_price   NUMERIC(18, 8) NOT NULL,
    close_price NUMERIC(18, 8) NOT NULL,
    volume      NUMERIC(24, 4) NOT NULL,
    PRIMARY KEY (asset_id, timeframe, timestamp)
);
SELECT create_hypertable('asset_prices', 'timestamp', chunk_time_interval => INTERVAL '3 months');

CREATE TABLE forum_scraped_data (
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
CREATE INDEX idx_forum_asset_time ON forum_scraped_data(asset_id, post_timestamp DESC);

CREATE TABLE market_alerts (
    id                   BIGSERIAL PRIMARY KEY,
    asset_id             INT         NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
    timeframe            VARCHAR(5)  NOT NULL,
    timestamp            TIMESTAMPTZ NOT NULL,
    engine_version       VARCHAR(20) NOT NULL,
    is_backtest          BOOLEAN     NOT NULL DEFAULT FALSE,

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

    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_alerts_training ON market_alerts(outcome) WHERE outcome IS NOT NULL;
CREATE INDEX idx_alerts_open     ON market_alerts(asset_id) WHERE outcome IS NULL;

CREATE TABLE alert_evidence (
    alert_id BIGINT NOT NULL REFERENCES market_alerts(id) ON DELETE CASCADE,
    post_id  BIGINT NOT NULL REFERENCES forum_scraped_data(id) ON DELETE CASCADE,
    weight   NUMERIC(5, 4) NOT NULL,               -- contribuição no sentimento agregado
    PRIMARY KEY (alert_id, post_id)
);
