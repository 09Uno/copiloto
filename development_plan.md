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

## 4. Schema

O DDL vive em [infra/schema.sql](infra/schema.sql) (idempotente, aplicado por `dands db init`).
As decisões e o porquê de cada uma estão em [ARCHITECTURE.md](ARCHITECTURE.md) §5 — este plano
não duplica o schema para não haver duas versões divergindo.

---

## 5. Fases de desenvolvimento

### ✅ Fase 0 — Fundação e Ingestão Histórica  *(concluída)*
Sem isso, não há backtest.

- [x] Repositório, CLI (`dands`), Parquet como camada de aterrissagem.
- [x] Supabase (Postgres gerenciado, sem Docker) — `dands db init` / `dands db load`.
- [x] **Ingestor Binance**: klines 15m e 1d. É o dataset mais limpo e mais longo que existe
      de graça — e a base de validação da estratégia.
- [x] **Ingestor EOD** (yfinance): diário de B3 e EUA.
- [x] Falha tratada como caso normal (retry, detecção de gaps, backfill idempotente).

**Resultado:** 3 anos · 323.880 velas · cobertura 100% e **zero gaps** em cripto (105.119 velas de
15m por par). Os dias úteis ausentes nas ações foram conferidos um a um: todos feriados de bolsa.

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

### Fase 3 — Motor em Produção + Monitoramento em Tempo Real
Só depois que a Fase 2 der sinal verde. **Especificado em detalhe em [ARCHITECTURE.md](ARCHITECTURE.md) §3.**

- Worker `stream_crypto`: WebSocket da Binance. Gatilho = `k.x == true` (**vela fechada**) — nunca a
  vela em formação, que faz o sinal *repintar* e destrói a correspondência com o backtest.
  Reconexão obrigatória com rebusca REST do intervalo perdido.
- Worker `ingest_eod`: APScheduler no **fuso da bolsa** (18:30 BRT / 17:00 ET), nunca em UTC fixo —
  o offset americano muda 2x por ano.
- Worker `close_alerts`: usa o preço **contínuo** (não o `close`) para saber se TP/SL foi tocado
  dentro da vela. Em ações, sem intrabar, assume o pior caso (stop primeiro).
- Alerta chega por **Telegram**. O dashboard é ferramenta de investigação, não de vigilância.
- FastAPI só de leitura + `/stream` (SSE) para o dashboard aberto. Auth = token estático único.
- **Decidir onde roda** (PC / VPS ~US$5 / cron REST) — a Fase 2 é quem autoriza esse gasto.

**Done quando:** o sistema gerar e fechar alertas sozinho por uma semana, e as métricas observadas
em produção baterem com as do backtest. Se divergirem muito, **há lookahead no backtest** — é o
canário mais barato que existe para esse bug.

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
