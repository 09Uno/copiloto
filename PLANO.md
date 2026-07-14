# Plano — Copiloto de Decisão

> O projeto muda de natureza. Ele deixa de tentar **prever** e passa a **decidir melhor**.
> Isto não é consolo: é a consequência direta do que os dados provaram.

---

## 0. O que aprendemos (e que define tudo o que vem abaixo)

Dois dias de medição, com dado oficial de 20 anos, sem viés de sobrevivência:

| O que testamos | Resultado |
|---|---|
| 6 estratégias (reversão, cross-sectional, momentum ×2, grid de 81, carteira sem stop) | nenhuma com borda out-of-sample |
| Features de **preço** (936.392 observações) | **AUC 0,487–0,515** |
| **Sentimento** de notícia (518 mil artigos, GDELT) | **AUC 0,494–0,504** |

`AUC 0,500 = cara ou coroa.` E o teste **detecta** informação quando ela existe (controle positivo:
feature que conhece o futuro → AUC 0,80). **Não há sinal a extrair.**

### As cinco regras que nascem disso

1. **O sistema NUNCA prevê preço.** Nem com score, nem com "68% de chance", nem com seta verde.
   O histórico diz ~47% para qualquer setup — mostrar outra coisa é inventar o número.
2. **A decisão vem de um critério SEU, não do mercado.** "Quero 8% de yield" é uma meta sua, e
   dela sai um preço teto objetivo. Isso não depende de adivinhar nada — e é por isso que funciona.
3. **Regras definidas a frio. Cobradas a quente.** O inimigo não é o mercado; é o você das 23h com
   o gráfico verde na tela. O sistema é um dispositivo de compromisso.
4. **Fato, não opinião.** Toda afirmação rastreável a um número e a uma fonte com data.
5. **A decisão é sempre sua.** O sistema informa, argumenta, barra — mas nunca decide.

---

## 1. Os módulos

### M1 · Tese — *o núcleo, e o que ninguém faz*

Na compra, você escreve **por que**. Com uma regra dura: **cada pilar precisa ser verificável**.

> ❌ "vai subir" · "empresa boa" — não é tese, é torcida
> ✅ "payout < 80%" · "dívida/EBITDA < 3,0" · "P/VP < 1,0" — cada pedaço é um número

O sistema relê a CVM a cada trimestre e checa **pilar por pilar**. Quando um cai, avisa:

```
⚠️  SAPR4 — 2 dos 5 pilares da sua tese caíram
    P/VP < 1,0        → hoje 1,24  ✗ (subiu, não está mais barata)
    dívida/EBITDA < 3 → hoje 3,6   ✗ (subiu no 2º e 3º tri)
    payout < 70%      → 64%        ✓
    yield > 6%        → 6,8%       ✓
    monopólio regulado             ✓

    Você compraria hoje, sabendo disso?
```

Ele **não diz "venda"**. Devolve a sua decisão com os fatos atualizados.

**Isso te impede das duas coisas:** fazer preço médio numa tese morta (a forma nº 1 de destruir
patrimônio) e vender um vencedor cuja tese está intacta (a nº 2).

---

### M2 · Preço teto e yield — *o critério ancorado no seu objetivo*

```
preço teto = dividendo por ação ÷ SUA meta de yield
```

Se a TAEE3 paga R$ 1,15 e sua meta é 8% → teto **R$ 14,38**. Acima disso, não entrega o que
você quer. **Não prevê nada** — só pergunta se, a este preço, você recebe o que decidiu receber.

Entrega:
- **Preço teto** por ativo (meta de yield configurável, por papel)
- **Yield-on-cost** sobre o seu custo médio real
- **Simulação de aporte:** *"comprar 100 a R$ 13,67 → custo médio vai a R$ 13,25, YoC de 8,74% → 8,68%"*
- **Múltiplos contra a PRÓPRIA história** (P/L e P/VP vs. a mediana de 10 anos do mesmo papel —
  comparar o P/L da Vale com o do Itaú não diz nada; contra a Vale de 10 anos, diz muito)

> **É assim que "euforia" vira número:** euforia é pagar um múltiplo que você nunca pagou antes.

---

### M3 · Guarda-corpo — *a defesa contra você mesmo*

```
🛑  Você está comprando TAEE3 a R$ 16,20.
    Seu teto (meta 8%): R$ 14,38 — você paga 13% acima do SEU limite.
    P/VP 1,6 → o papel só esteve tão caro 2 vezes em 10 anos.

    Você mesmo escreveu a regra. Quer quebrá-la?
    Se sim, escreva o porquê — fica registrado.
```

Ele **não te impede** (o dinheiro é seu). Ele te obriga a olhar no olho da sua própria regra e
**escrever a desculpa**. É muito mais difícil se enganar por escrito do que de cabeça.

E o mesmo do outro lado — barra a **venda nervosa** quando nenhum critério de venda foi acionado.

**O placar, depois de um ano:**

```
Das suas 23 compras:
  17 respeitaram suas regras  →  +9,4% em média
   6 quebraram suas regras    →  -14,1% em média
  As compras feitas empolgado custaram R$ 2.300.
```

> Nada muda comportamento como ver, **em reais**, o preço da própria empolgação.

---

### M4 · Realização de lucro e rebalanceamento

**Gatilho duplo** (nenhum dos dois sozinho basta):
- **esticado** (acima do teto / múltiplo em extremo histórico) **E**
- **pilar de tese caído**

Só esticado → você corta a flor. Só tese caída → você vende no pânico junto com todo mundo.
**Os dois juntos** → o mercado ainda paga caro por algo que já não é o que você comprou.

Os **quatro motivos legítimos** de venda, todos sem previsão:
1. **Tese quebrou** — o ativo não é mais o que você comprou (vende no verde *e* no vermelho)
2. **Deixou de servir ao objetivo** — *"quem compra hoje recebe 6,1%; a SAPR4 paga 9,2%. Rotacionar
   aumenta sua renda em R$ 340/ano; custo fiscal R$ 0 (dentro da isenção). Paga-se imediatamente."*
3. **Concentração** — virou 28% da carteira com alvo de 10%. Não é apostar contra: é não deixar
   uma empresa decidir sua aposentadoria.
4. **Imposto** — ver M5.

**Trava anti-giro** (o medo legítimo por trás do "não quero rebalancear à toa"):
- gatilho **raro**: desvio grande ou pilar caindo — nunca oscilação
- *"você já rebalanceou 3× este ano; cada rodada custa corretagem e imposto"*
- **placar do giro:** *"seus rebalanceamentos renderam +R$ 120 e custaram R$ 380"*

> **SEM filtro de cor.** O preço que você pagou é custo afundado — o mercado não sabe e não se
> importa. Filtrar por "só no verde" faria o sistema podar as flores (ITUB4, BBDC4, TAEE3) e nunca
> olhar as ervas (GOLD11 −12%, ROXO34 −8%) — que são justamente as candidatas a tese quebrada.
> É o **efeito disposição**, o viés mais caro do varejo, automatizado com a minha assinatura embaixo.

---

### M5 · Imposto — *dinheiro puro, zero previsão*

O que a lei diz (e o que muda a decisão):
- **Ações:** ganho **isento** se as **vendas do mês** somarem até **R$ 20.000**. Acima disso, 15%
  sobre o ganho — *de todas as vendas do mês*.
- **FII:** **20%**, sem isenção, sempre.
- **Prejuízo realizado:** vira **crédito que abate lucros futuros, sem prazo** — é um **ativo fiscal**.

O que o sistema faz:
```
Você quer vender R$ 32 mil de ITUB4 (lucro R$ 6 mil).
  tudo agora            → passa dos R$ 20 mil → imposto R$ 900
  R$ 19 mil + R$ 13 mil → dois meses, ambos isentos → imposto R$ 0

Você tem R$ 484 de prejuízo em BBDC3 — abate lucro futuro. Vale R$ 72.
```

Alerta contínuo: *"você já vendeu R$ 18.500 em ações este mês. Mais uma venda e você perde a
isenção — e paga 15% sobre TODO o ganho do mês."*

---

### M6 · Risco real da carteira

> **"Você acha que tem 13 ativos. Quantas apostas você tem?"**

ITUB4 + BBDC4 + SANB11 são o **mesmo trade**. TAEE3 + CMIG4 + SAPR4 são todas *utilities*
reguladas — sobem e caem juntas com a curva de juros.

Com 20 anos de dado, calculo a **correlação real** entre as suas posições. Se a média for 0,85,
você tem **três apostas com treze nomes** — e o drawdown na próxima crise será o dobro do que
você espera. É **prospectivo**: diz o risco que você corre *agora*.

Mais: **benchmark contínuo** contra BOVA11 e CDI, com o método certo (time-weighted, que remove
o efeito do aporte e mede só a **decisão**).

> Já rodado com o seu extrato: nos últimos 10 meses, sua carteira B3 rendeu **+7,36%** contra
> **+5,24%** do BOVA11. **Mas 10 meses não provam nada** — o mesmo rigor que reprovou as
> estratégias se aplica a você. Em 3 anos, saberemos.

---

### M7 · Swing — *disciplina e placar, nunca sinal*

A escolha do **quê** comprar continua **100% sua**. O sistema entra depois:

- **Quanto comprar** (1% de risco → o stop define a quantidade)
- **Onde o stop faz sentido** (ATR — volatilidade real, não palpite)
- **R:R da operação** pelo seu próprio critério
- **Você já está exposto?** *"quer PRIO3, mas já tem 22% em petróleo"*
- **Impacto fiscal** da venda
- **O placar honesto:** *"seus últimos 40 swings deram −R$ 300. O buy & hold no mesmo período deu +R$ 900."*

> **Nunca haverá sinal de entrada.** Uma tela bonita com RSI e bandas te daria **confiança sem
> vantagem** — e essa é a combinação que mais destrói patrimônio: você opera mais, com convicção,
> e o custo cobra.

### ❌ Day trade — não será construído

No gráfico de 15 minutos, o stop fica a ~0,7% do preço e o custo de ida e volta é 0,30%: **o custo
sozinho come metade do risco de cada operação** (medido: perda média de −1,44R onde deveria ser
−1,0R). Mesmo escolhendo perfeitamente, a matemática já sangra. Uma ferramenta de day trade seria
uma ferramenta para perder mais rápido e com mais confiança.

---

## 2. Ordem de construção

| Fase | O quê | Por que primeiro |
|---|---|---|
| **A** | **Dados: CVM (ITR/DFP) + dividendos** | É o material que o analista **lê**. Sem isso, nada acima existe. A CVM publica com **data de publicação** → point-in-time de verdade, sem lookahead. |
| **B** | **M2 — preço teto, yield-on-cost, simulação de aporte** | Valor imediato, e é o **critério** de que tudo depende. |
| **C** | **M1 — tese** (registro, verificação trimestral, alertas) | O núcleo. Precisa de A e B. |
| **D** | **M3 — guarda-corpo** + placar de disciplina | Precisa de B e C para saber o que barrar. |
| **E** | **M5 — imposto** | Independente. Dinheiro imediato. Pode andar em paralelo. |
| **F** | **M4 — realização e rebalanceamento** | Precisa de C (tese) e E (imposto na conta). |
| **G** | **M6 — risco real** (correlação, benchmark) | Independente. Usa o que já temos. |
| **H** | **M7 — swing** (sizing, placar) | Por último. É o menos valioso dos que sobraram. |

---

## 3. O que precisa ser verificado antes de prometer

Honestidade sobre o que ainda **não sei**:

- [ ] **Consenso de analistas** (alvo médio, nº de analistas) existe para ação brasileira via
      `yfinance`? Provável, mas **não verificado**. Se não existir, o módulo cai — e eu aviso.
- [ ] **Estrutura da CVM** (ITR/DFP em `dados.cvm.gov.br`): formato, cobertura, data de publicação.
- [ ] **Histórico de dividendos (DPA)** confiável por papel — base do preço teto.
- [ ] **Isenção de R$ 20 mil**: confirmar a regra vigente (vendas do mês, só ações, não FII/ETF/BDR).

---

## 4. O que fica do trabalho anterior

Nada foi jogado fora:

- **20 anos de B3 oficial** (COTAHIST), ajustado por evento corporativo — pegou um "crash de −50%"
  fantasma no BBAS3 que teria envenenado tudo
- **Universo point-in-time** com os 283 papéis que morreram (viés de sobrevivência eliminado)
- **Sentimento de notícia** (GDELT, 2017→hoje) — como **contexto**, jamais como sinal
- **O laboratório** (`dands backtest`, `dands informacao`) — mede qualquer hipótese futura, sua ou
  de terceiros. Da próxima vez que alguém te vender um método, **você mede em vez de acreditar.**
