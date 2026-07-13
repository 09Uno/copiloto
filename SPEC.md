# SPEC — Motor Quantamental

Especificação funcional do motor. É a referência de **o que calcular** — a fonte da verdade para
implementar a Fase 1 (indicadores) e a Fase 2 (backtest) do [plano de desenvolvimento](development_plan.md).

Ferramenta de **uso próprio**, single-user, self-hosted. Sem multi-tenancy, sem billing,
sem distribuição de sinais a terceiros.

---

## 1. Escopo: matriz mercado × horizonte

O motor é **um só**. O que muda por mercado é o conector de ingestão e o timeframe habilitado.

| Mercado | Fonte | Day Trade (15m) | Swing (1d) | Longo Prazo |
|---|---|---|---|---|
| Cripto | Binance (REST + WebSocket) | ✅ tempo real | ✅ | ⚠️ sem fundamentos clássicos |
| Ações EUA | yfinance | ❌ delay de 15min inviabiliza reversão intradiária | ✅ EOD | ✅ balanços via yfinance |
| Ações B3 | brapi.dev (primário), yfinance (fallback) | ❌ delay + cobertura intraday ruim | ✅ EOD | ✅ |
| Opções | — | — | — | ⚠️ grade de opções não tem fonte gratuita confiável; reavaliar antes de investir tempo |

Nenhuma fonte tem SLA. O ingestor trata falha, gap e backfill como caso **normal**, não como exceção.

---

## 2. Features (calculadas por ativo × timeframe, a cada vela fechada)

Entrada: DataFrame OHLCV. Saída: as features abaixo. Módulo puro, sem I/O.

### 2.1 Regressão linear sobre log-preço
Ajuste de `ln(close)` contra o índice temporal, janela de `N` velas:

```
ln(P_t) = α + β·t + ε
```

- `regression_slope` = β → retorno log por período. **Sobre log-preço, não preço bruto**, senão o slope
  de BTC (dezenas de milhares) e de PETR4 (dezenas) não são comparáveis nem entre si nem no tempo.
- `regression_r2` = R² do ajuste → mede **quão bem definida** é a tendência. É o que separa regime.

### 2.2 Bandas de desvio padrão
Sobre `close`, janela `janela_media`:

- `μ` = média móvel
- `σ` = desvio padrão da janela
- `deviation_from_mean` = `(close − μ) / σ` → distância em desvios padrão (ex: `−2.15`)

> **Nota:** a premissa de que ±2σ contém 95% do tempo é **falsa** para retornos financeiros
> (caudas gordas, curtose alta). A banda é uma heurística de exaustão; o limiar real é
> **calibrado empiricamente no backtest**, não assumido da distribuição normal.

### 2.3 Z-score de volume
Sobre **`ln(volume)`**, não volume bruto (a distribuição de volume é lognormal-ish; o z-score cru
é mal-comportado e dispara falso a toda hora):

```
volume_z_score = (ln(V_t) − μ_lnV) / σ_lnV
```

### 2.4 ATR (Average True Range)
Janela `atr_janela`. Base do dimensionamento de risco.

### 2.5 Regime de mercado
Classificação derivada de `regression_r2`, `|regression_slope|` e da volatilidade recente:

| Regime | Condição | Comportamento do motor |
|---|---|---|
| `LATERAL` | R² < `r2_max_lateral` | **Opera reversão à média.** É o único regime onde a tese vale. |
| `TENDENCIA` | R² alto + \|slope\| alto | **Não opera reversão.** Tocar −2σ aqui é continuação, não exaustão — comprar é pegar faca caindo. |
| `NERVOSO` | choque de volatilidade / z-score de volume extremo | Sinal suprimido ou marcado como alto risco. |

---

## 3. Regra de sinal (determinística — Fase 1, sem ML)

Um sinal de **compra** exige, cumulativamente:

1. `market_regime == LATERAL`
2. `deviation_from_mean <= −n_sigma_entrada`
3. `volume_z_score >= z_minimo`
4. O filtro de risco:retorno (§4) passa

Venda é o espelho (`deviation_from_mean >= +n_sigma_entrada`).

O `calculated_score` (0–100) é uma combinação ponderada e **explicável** das features acima.
Pesos fixos nesta fase. Nada de ML — o ML só entra na Fase 6, e só se bater este baseline fora da amostra.

---

## 4. Gerenciamento de risco

```
stop_loss     = trigger − 1.5 × ATR        (compra; espelhado na venda)
take_profit   = μ  (a linha da regressão / média central — o alvo natural da reversão)
```

**Filtro de descarte:** se `|take_profit − trigger| < rr_minimo × |trigger − stop_loss|`, o sinal
é descartado. O R:R **não é uma promessa, é um critério de eliminação**.

> Isso corrige a contradição do documento original, que mandava comprar em −2σ com alvo em μ e stop
> em −3.2σ (ganho de 2σ contra risco de 1.2σ = **1.67:1**) enquanto exigia um mínimo de 1:2 — as duas
> regras se anulavam e o sistema descartaria todos os próprios sinais.

**Custos.** Toda métrica é **líquida** de corretagem, spread e slippage. Uma estratégia lucrativa só
antes de custos é uma estratégia que perde dinheiro — e em intradiário o custo come a maior parte da borda.

---

## 5. Rotulagem do desfecho — Triple Barrier

Três barreiras, avaliadas em ordem cronológica a partir do `trigger`:

| Barreira | `outcome` |
|---|---|
| Preço toca `take_profit` primeiro | `TP` |
| Preço toca `stop_loss` primeiro | `SL` |
| Nenhuma das duas dentro de `horizonte_max` | `TIMEOUT` — o retorno na expiração **é** o rótulo (não é NULL) |

**Desempate:** se alvo e stop caem dentro da **mesma vela**, o OHLC não diz qual veio primeiro.
Resolver com dados de timeframe menor. Ignorar isso vaza otimismo para dentro do backtest.

`outcome_return` é sempre **líquido de custos**.

---

## 6. Sentimento (Fase 5 — depois do motor funcionar)

Deliberadamente posterior: o sinal quantitativo precisa ter borda **sozinho** antes de tentar
melhorá-lo com texto, senão não há como medir se o texto ajudou.

- **Fontes:** Reddit (PRAW, com credencial), feeds RSS de portais econômicos.
  **Não raspar ADVFN nem fóruns da B3** — viola os termos de uso e cai em Cloudflare na primeira semana.
- **Modelo por idioma:** FinBERT (inglês) / BERTimbau financeiro ou equivalente (português).
  FinBERT é treinado em inglês — aplicá-lo a texto PT-BR produz ruído com aparência de sinal.
- **Agregação** ponderada por engajamento e recência → `aggregated_sentiment`, com os posts
  que contribuíram registrados em `alert_evidence` (é isso que torna a tela de justificativa possível).
- **Critério de adoção:** só entra na regra se **melhorar a expectância no backtest**.

---

## 7. Hiperparâmetros

Valores **iniciais**. A calibração é *output* da Fase 2 (backtest), não input.

```yaml
regressao:
  janela: 100            # velas
  base: log_preco
bandas:
  janela_media: 20
  n_sigma_entrada: 2.0
regime:
  r2_max_lateral: 0.30   # acima disso = tendência → não opera reversão
volume:
  janela_zscore: 50
  z_minimo: 2.0
  base: log_volume
risco:
  atr_janela: 14
  stop_atr_mult: 1.5
  rr_minimo: 2.0
  horizonte_max:
    15m: 24              # velas (~6h)
    1d: 10               # dias
custos:
  cripto_taker_pct: 0.10
  acoes_br_pct: 0.05
  slippage_pct: 0.05
```

---

## 8. Carteira, execução e o que se aprende com ela

### 8.1 Banca por moeda

Uma `account` por moeda: **BRL** (B3) e **USD** (ações EUA + cripto; USDT conta como USD).
A visão consolidada converte por `fx_rates` (USDBRL diário, `BRL=X` no yfinance).

Somar tudo num número só esconde a pergunta que importa: um "+3% na semana" pode ser
**puro dólar subindo**, sem que nenhuma operação tenha dado certo. Separar as bancas mantém
resultado de operação e resultado cambial visíveis lado a lado.

### 8.2 Sizing — risco fixo por operação

Sem tamanho de posição, o stop loss é decorativo. O sistema dimensiona a partir do stop
que o motor já calculou (§4):

```
qty = (banca × risco_por_trade) / |entrada − stop|      # risco_por_trade = 1% por padrão
```

Ou seja, o alerta não diz só "compre" — diz **quanto**. E o campo de execução já vem preenchido
com esse número.

### 8.3 O botão Confirmar — dois níveis, não um

O alerta traz o que o **motor sugeriu** (`market_alerts`: trigger, TP, SL, qty). Ao confirmar,
você corrige para o que **de fato executou** (preço de preenchimento e quantidade reais) e isso
vira um `trade`. Os dois registros coexistem; é a diferença entre eles que carrega a informação.

**O alvo e o stop NÃO se movem quando seu preenchimento é pior.** Se o motor disse "compra a 100,
stop 97, alvo 106" e você entrou a 100.80, a tentação é reajustar tudo para preservar o R:R de 1:2.
Isso é enganar a si mesmo: 97 e 106 vêm do ATR e da linha de regressão — são **níveis do mercado**,
e o mercado não se moveu porque você pagou mais caro. O que piorou foi o *seu* risco-retorno
(de 2.0 para 1.6). O sistema **recalcula o `rr_real` no preenchimento e avisa** quando ele cai
abaixo do `rr_minimo`: você entrou numa operação pior do que a que o motor aprovou, e é melhor
ver isso na hora do que no fim do mês.

### 8.4 O que a execução ensina

**Slippage real** (`trade.entry_price` − `alert.trigger_price`) alimenta o `custos:` do §7, que hoje
é um chute de 0.05%. O backtest passa a rodar com o **seu** custo, e não com um número inventado.

**Meta-labeling** (López de Prado) — o uso correto dos trades confirmados no ML:

> **Nunca treine o preditor apenas nos alertas que você confirmou.** Parece óbvio e é veneno:
> você confirma talvez 5% dos alertas, escolhidos pelo seu gosto. Um modelo treinado nesse
> subconjunto aprende a **imitar a sua seleção**, não a prever o mercado — e você termina com
> uma cópia dos seus vieses, com verniz de estatística.

O dataset de previsão continua sendo **todos os alertas**, rotulados pela barreira tripla (§5)
independentemente de você ter operado — isso não tem viés de seleção. Os trades confirmados
treinam um **segundo** modelo, por cima: o primário diz a direção; o meta-modelo aprende **o seu
filtro** (confirmou / ignorou) e decide se vale entrar e com que tamanho. Assim dá para medir se
o seu filtro bate o modelo sozinho — e desligá-lo se não bater.

### 8.5 Métricas da banca

De `equity_snapshots` (um fecho por dia, por conta): ganho hoje / semana / mês / ano, em % e em
valor. E o **drawdown máximo real** — o número que de fato importa e que quase ninguém olha —
que sai de graça da mesma curva, comparável com o drawdown do backtest.

---

## 9. Analogia histórica (pgvector)

Onde vetores **não** ajudam: embedding de série de preço. Preço é numérico e de baixa dimensão;
um vetor de features com distância euclidiana funciona melhor e é interpretável. Vector DB para
preço seria modinha.

Onde ajudam de verdade — **"o que aconteceu das outras vezes que o mercado esteve assim?"**

Cada alerta guarda o estado do mercado como um vetor de 5 features **naturalmente adimensionais**:

```
state_vector = [ slope_norm, r2, deviation_from_mean, volume_z_score, atr/close ]
```

> Elas já são escala-livre de propósito. Se precisássemos *ajustar* um normalizador sobre o
> histórico inteiro para construir o vetor, o próprio normalizador veria o futuro — é um vazamento
> sutil e clássico. Features adimensionais por construção eliminam o problema.

Com `pgvector`, cada alerta novo pergunta ao banco quais foram os **k momentos históricos mais
parecidos** e o que aconteceu depois deles:

> *"Este setup se pareceu com 50 casos passados: 32 bateram o alvo, 18 estoparam — 64% histórico"*,
> com os cinco gráficos mais parecidos ao lado.

Isso é explicabilidade de verdade, **funciona com pouquíssimo dado** (kNN não precisa dos milhares
de exemplos de um XGBoost) e existe já na Fase 2 — muito antes do ML da Fase 6. Vira até uma
feature do score.

**A busca só pode olhar vizinhos estritamente anteriores** (`WHERE timestamp < :agora`). Um kNN
ingênuo sobre a tabela inteira enxerga o futuro e devolve uma taxa de acerto fantástica e falsa.

**Segundo uso, na Fase 5:** embedding de texto para **deduplicação semântica de notícia**. A mesma
manchete replicada em 20 fóruns não são 20 sinais — mas a agregação ponderada por engajamento a
contaria 20 vezes e inflaria o pânico. Sem isso, o `aggregated_sentiment` estaria errado em silêncio.

---

## 10. Longo prazo / fundamentalista (Fase 7)

Independente do motor de reversão — pode ser desenvolvido em paralelo.

- Balanços trimestrais via `yfinance` (`.financials`, `.balance_sheet`).
- Modelos clássicos: Graham, Gordon, múltiplos (P/L, EV/EBITDA) comparados contra a **mediana
  histórica do próprio ativo** e contra o setor.
- Sem ML. É aritmética contábil — e é explicável por construção.
