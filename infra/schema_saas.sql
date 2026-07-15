-- Multi-tenant, PORTÁVEL. Roda igual no Supabase de hoje e no Postgres da VPS amanhã.
-- Aplicado depois de infra/schema.sql. Idempotente.
--
-- **Sem NENHUMA dependência de Supabase.** A primeira versão usava `auth.users` e `auth.uid()`
-- — que só existem no Supabase e quebrariam na VPS. Aqui o auth é da própria aplicação: uma
-- tabela `users`, senha com hash, token emitido pela API. A migração para a VPS é só apontar
-- a DATABASE_URL para o outro Postgres.
--
-- O CORTE que faz o multi-tenant custar quase nada: o dado da esteira é PÚBLICO (o LPA da
-- Petrobras é igual para todos). `fundamentos` é compartilhada e é a que dá trabalho — um
-- usuário novo NÃO gera ingestão. Só as tabelas do usuário levam user_id.

CREATE EXTENSION IF NOT EXISTS pgcrypto;  -- gen_random_uuid()

-- ============================================================================
-- USUÁRIOS — auth próprio, portável
-- ============================================================================

CREATE TABLE IF NOT EXISTS users (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email       TEXT UNIQUE NOT NULL,
    senha_hash  TEXT NOT NULL,        -- bcrypt; a senha em claro nunca toca o banco
    nome        TEXT,
    criado_em   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ultimo_login TIMESTAMPTZ
);

-- ============================================================================
-- PÚBLICO — sem dono, compartilhado. A esteira (Python, 1x/dia) escreve aqui.
-- ============================================================================
--
-- `data_publicacao` é o que torna a análise honesta: sem ela o sistema "saberia" em 30/09 um
-- resultado que só virou público em 12/11.

CREATE TABLE IF NOT EXISTS fundamentos (
    ticker           VARCHAR(20) NOT NULL,
    classe           VARCHAR(15) NOT NULL,       -- ACAO | FII
    data_base        DATE        NOT NULL,
    data_publicacao  DATE        NOT NULL,       -- ← point-in-time

    lpa              NUMERIC(18, 6),
    vpa              NUMERIC(18, 6),
    dpa              NUMERIC(18, 6),             -- dividendo/ação · rendimento/cota
    roe              NUMERIC(10, 6),
    payout           NUMERIC(10, 6),
    margem           NUMERIC(10, 6),
    divida_ebit      NUMERIC(12, 4),
    cresc_lucro      NUMERIC(12, 6),
    cresc_receita    NUMERIC(12, 6),
    p_vp             NUMERIC(12, 6),             -- FII
    alavancagem      NUMERIC(10, 6),             -- FII
    pct_imovel       NUMERIC(6, 4),
    pct_papel        NUMERIC(6, 4),
    pct_fii          NUMERIC(6, 4),
    financeira       BOOLEAN NOT NULL DEFAULT FALSE,

    atualizado_em    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (ticker, data_base)
);
CREATE INDEX IF NOT EXISTS idx_fund_pub ON fundamentos(ticker, data_publicacao DESC);

-- ============================================================================
-- DO USUÁRIO — user_id
-- ============================================================================

-- **Fonte de carteira PLUGÁVEL.** FinControl é UMA fonte; amanhã CSV, nota de corretagem,
-- API de corretora — sem tocar em mais nada.
CREATE TABLE IF NOT EXISTS carteira_fontes (
    id          BIGSERIAL PRIMARY KEY,
    user_id     UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    tipo        VARCHAR(20) NOT NULL,     -- 'MANUAL' | 'FINCONTROL' | ...
    config      JSONB       NOT NULL DEFAULT '{}',
    ativa       BOOLEAN     NOT NULL DEFAULT TRUE,
    ultima_sync TIMESTAMPTZ,
    criada_em   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_fontes_user ON carteira_fontes(user_id);

CREATE TABLE IF NOT EXISTS posicoes (
    id            BIGSERIAL PRIMARY KEY,
    user_id       UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    ticker        VARCHAR(20) NOT NULL,
    classe        VARCHAR(15) NOT NULL,
    quantidade    NUMERIC(24, 8) NOT NULL,
    custo_medio   NUMERIC(18, 8) NOT NULL,
    fonte         VARCHAR(20) NOT NULL DEFAULT 'MANUAL',
    atualizada_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_posicao UNIQUE (user_id, ticker)
);

-- As teses ganham dono. (A tabela vem de infra/schema.sql; aqui só o vínculo com o usuário.)
ALTER TABLE teses DROP CONSTRAINT IF EXISTS teses_user_id_fkey;
ALTER TABLE teses ADD COLUMN IF NOT EXISTS user_id UUID;
ALTER TABLE teses ADD CONSTRAINT teses_user_id_fkey
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;
CREATE INDEX IF NOT EXISTS idx_teses_user ON teses(user_id) WHERE encerrada_em IS NULL;

-- A meta de yield é DO USUÁRIO — é dela que sai o preço teto. Isso é o que torna a ferramenta
-- defensável: o critério é do usuário, não uma recomendação nossa.
CREATE TABLE IF NOT EXISTS preferencias (
    user_id           UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    meta_yield_acao   NUMERIC(5, 4) NOT NULL DEFAULT 0.06,
    meta_yield_fii    NUMERIC(5, 4) NOT NULL DEFAULT 0.10,
    email_alertas     BOOLEAN       NOT NULL DEFAULT TRUE,
    criado_em         TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

-- ---------------------------------------------------------------- isolamento
--
-- A API filtra por user_id em toda query (guarda primária). RLS entra como defesa em
-- profundidade ANTES do primeiro usuário pago — não agora: com um único usuário ela protege
-- zero e só adiciona atrito. O padrão portável (funciona no Supabase E no Postgres puro) é
-- `current_setting('app.user_id')`, com a API fazendo `set_config` por transação. Fica
-- documentado aqui para quando o momento chegar.
