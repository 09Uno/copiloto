-- Multi-tenant. Aplicado DEPOIS de infra/schema.sql.
--
-- **O corte que faz isto ser fácil:** o dado que a esteira produz é PÚBLICO — o LPA da
-- Petrobras é o LPA da Petrobras, igual para todo mundo. Só as tabelas DO USUÁRIO precisam de
-- `user_id` e RLS. E `fundamentos`, que é a que custa caro para construir, é compartilhada:
-- **um usuário novo não gera nenhum trabalho de ingestão.**

-- ============================================================================
-- PÚBLICO — sem user_id, compartilhado
-- ============================================================================
--
-- A esteira (Python, 1x/dia) escreve aqui. Ninguém mais escreve.
-- `data_publicacao` é o que torna a análise honesta: sem ela, o sistema "saberia" em 30/09 um
-- resultado que só virou público em 12/11.

CREATE TABLE IF NOT EXISTS fundamentos (
    ticker           VARCHAR(20) NOT NULL,
    classe           VARCHAR(15) NOT NULL,       -- ACAO | FII
    data_base        DATE        NOT NULL,       -- o trimestre a que se refere
    data_publicacao  DATE        NOT NULL,       -- quando virou público  ← point-in-time

    -- métricas canônicas (o NOME é a interface; o rótulo é a tela)
    lpa              NUMERIC(18, 6),
    vpa              NUMERIC(18, 6),
    dpa              NUMERIC(18, 6),             -- dividendo/ação · rendimento/cota
    roe              NUMERIC(10, 6),
    payout           NUMERIC(10, 6),
    margem           NUMERIC(10, 6),
    divida_ebit      NUMERIC(12, 4),
    cresc_lucro      NUMERIC(12, 6),
    cresc_receita    NUMERIC(12, 6),
    p_vp             NUMERIC(12, 6),             -- FII: preço/VP da cota
    alavancagem      NUMERIC(10, 6),             -- FII: passivo/PL
    pct_imovel       NUMERIC(6, 4),              -- FII: composição real do ativo
    pct_papel        NUMERIC(6, 4),
    pct_fii          NUMERIC(6, 4),
    financeira       BOOLEAN NOT NULL DEFAULT FALSE,  -- banco: EBIT e dívida não se aplicam

    atualizado_em    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (ticker, data_base)
);
CREATE INDEX IF NOT EXISTS idx_fund_pub ON fundamentos(ticker, data_publicacao DESC);

ALTER TABLE fundamentos ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS fundamentos_leitura ON fundamentos;
CREATE POLICY fundamentos_leitura ON fundamentos FOR SELECT TO authenticated USING (true);

-- ============================================================================
-- DO USUÁRIO — user_id + RLS
-- ============================================================================

-- **Fonte de carteira PLUGÁVEL.** O FinControl é UMA fonte; amanhã entra CSV, nota de
-- corretagem ou outra corretora — sem tocar em mais nada. Mesma lógica das classes de ativo:
-- o resto do sistema não sabe de onde a posição veio.
CREATE TABLE IF NOT EXISTS carteira_fontes (
    id          BIGSERIAL PRIMARY KEY,
    user_id     UUID        NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    tipo        VARCHAR(20) NOT NULL,     -- 'MANUAL' | 'FINCONTROL' | 'CSV' | ...
    config      JSONB       NOT NULL DEFAULT '{}',  -- credenciais/URL da fonte
    ativa       BOOLEAN     NOT NULL DEFAULT TRUE,
    ultima_sync TIMESTAMPTZ,
    criada_em   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Posições. Vêm da fonte (sincronizadas) ou são digitadas (fonte MANUAL).
CREATE TABLE IF NOT EXISTS posicoes (
    id           BIGSERIAL PRIMARY KEY,
    user_id      UUID        NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    ticker       VARCHAR(20) NOT NULL,
    classe       VARCHAR(15) NOT NULL,
    quantidade   NUMERIC(24, 8) NOT NULL,
    custo_medio  NUMERIC(18, 8) NOT NULL,
    fonte        VARCHAR(20) NOT NULL DEFAULT 'MANUAL',
    atualizada_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_posicao UNIQUE (user_id, ticker)
);

-- As teses ganham dono.
ALTER TABLE teses ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES auth.users(id)
    ON DELETE CASCADE;
CREATE INDEX IF NOT EXISTS idx_teses_user ON teses(user_id) WHERE encerrada_em IS NULL;

-- Meta de yield por usuário (o teto vem DELE, não do mercado — é o que torna a
-- ferramenta defensável: o critério é do usuário, não uma recomendação nossa).
CREATE TABLE IF NOT EXISTS preferencias (
    user_id           UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    meta_yield_acao   NUMERIC(5, 4) NOT NULL DEFAULT 0.06,
    meta_yield_fii    NUMERIC(5, 4) NOT NULL DEFAULT 0.10,
    email_alertas     BOOLEAN       NOT NULL DEFAULT TRUE,
    criado_em         TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

-- ---------------------------------------------------------------- RLS
--
-- Defesa em profundidade: a API já filtra por user_id, mas o RLS garante que um bug na API
-- não vaze a carteira de um usuário para outro.

ALTER TABLE carteira_fontes ENABLE ROW LEVEL SECURITY;
ALTER TABLE posicoes        ENABLE ROW LEVEL SECURITY;
ALTER TABLE teses           ENABLE ROW LEVEL SECURITY;
ALTER TABLE preferencias    ENABLE ROW LEVEL SECURITY;

DO $$
DECLARE t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY['carteira_fontes', 'posicoes', 'teses', 'preferencias'] LOOP
        EXECUTE format('DROP POLICY IF EXISTS %I_dono ON %I', t, t);
        EXECUTE format(
            'CREATE POLICY %I_dono ON %I FOR ALL TO authenticated '
            'USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid())', t, t
        );
    END LOOP;
END $$;

-- Pilares e checagens herdam o dono pela tese.
ALTER TABLE tese_pilares   ENABLE ROW LEVEL SECURITY;
ALTER TABLE tese_checagens ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS pilares_dono ON tese_pilares;
CREATE POLICY pilares_dono ON tese_pilares FOR ALL TO authenticated
    USING (EXISTS (SELECT 1 FROM teses WHERE teses.id = tese_id AND teses.user_id = auth.uid()))
    WITH CHECK (EXISTS (SELECT 1 FROM teses WHERE teses.id = tese_id
                        AND teses.user_id = auth.uid()));

DROP POLICY IF EXISTS checagens_dono ON tese_checagens;
CREATE POLICY checagens_dono ON tese_checagens FOR ALL TO authenticated
    USING (EXISTS (SELECT 1 FROM teses WHERE teses.id = tese_id AND teses.user_id = auth.uid()))
    WITH CHECK (EXISTS (SELECT 1 FROM teses WHERE teses.id = tese_id
                        AND teses.user_id = auth.uid()));
