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

## 8. Longo prazo / fundamentalista (Fase 7)

Independente do motor de reversão — pode ser desenvolvido em paralelo.

- Balanços trimestrais via `yfinance` (`.financials`, `.balance_sheet`).
- Modelos clássicos: Graham, Gordon, múltiplos (P/L, EV/EBITDA) comparados contra a **mediana
  histórica do próprio ativo** e contra o setor.
- Sem ML. É aritmética contábil — e é explicável por construção.
