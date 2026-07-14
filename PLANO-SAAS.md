# Plano — o SaaS

> O copiloto de decisão vira produto. Separado do FinControl (que é gestão financeira);
> aqui é **decisão de investimento**.

---

## 1. A linha que não se cruza

Antes da stack, antes de tudo. **Uso próprio não é regulado. Cobrar de terceiros, é.**

No Brasil, produzir **análise de valores mobiliários** para terceiros exige analista com CNPI e
registro (CVM 20/2021). **Recomendação personalizada** é consultoria (CVM 19/2021).

**A arquitetura já está do lado certo — por princípio, não por sorte:**

| O sistema FAZ | O sistema NUNCA faz |
|---|---|
| Mostra o **fato** (payout 82%, dívida 3,9×, lucro −48%) | Diz "compre" ou "venda" |
| Calcula o teto a partir da **meta de yield DO USUÁRIO** | Dá "score de oportunidade" |
| Checa a tese que **o usuário escreveu** | Sugere qual ação comprar |
| Devolve a decisão: *"você compraria hoje, sabendo disso?"* | Prevê preço |

É **ferramenta de cálculo sobre dado público** — o critério é do usuário. Mesmo espírito de
Status Invest e Investidor10, que operam sem registro na CVM.

> **Isto não é parecer jurídico.** Antes de cobrar: conversar com alguém de mercado de capitais.
> Mas se chega nessa conversa com a arquitetura certa — e isso vale muito.

### Proibido, para sempre

❌ Botão de "oportunidade" · "recomendamos" · "score de compra" · ranking de "melhores ações"
❌ Qualquer previsão de preço

Não é só risco regulatório: **é a mentira que dois dias de backtest destruíram** (AUC 0,50 no
preço e na notícia, em 936 mil observações). Um score fabricado dá **convicção sem vantagem** —
e é isso que faz o usuário operar mais e perder mais.

---

## 2. Stack

| Camada | Escolha | Por quê |
|---|---|---|
| Frontend | **Next.js 15 + shadcn/ui + Tailwind** | pedido do dono; componentes que se copia para dentro do projeto (sem lock-in de biblioteca) |
| API | **FastAPI (Python)** | **todo o trabalho difícil já está aqui.** Os 7 bugs da CVM, o point-in-time, o motor da tese, o backtest. Reescrever seria jogar fora meses. |
| Banco + Auth | **Supabase** | já em uso. Postgres + Auth + RLS de graça. |
| Esteira de dados | **Python, batch diário** | não conhece usuário. Roda sozinha. |

---

## 3. O corte que faz o multi-tenant ser fácil

**O dado que produzimos é PÚBLICO — igual para todo mundo.** O LPA da Petrobras é o LPA da
Petrobras. Não depende de usuário nenhum.

```
   ESTEIRA (Python, 1x/dia, sem usuário)
   CVM · COTAHIST · FII · GDELT
        ↓  (os 7 bugs já resolvidos)
   tabela `fundamentos`  ←── PÚBLICA, sem user_id, uma linha por (ticker, trimestre)
        │
        │  Postgres (Supabase)
        ▼
   API (FastAPI)  ──►  Next.js + shadcn
        ▲
        │
   tabelas DO USUÁRIO  ←── user_id + RLS
   posicoes · teses · tese_pilares · tese_checagens · alertas
```

**Só as tabelas do usuário precisam de `user_id` e RLS.** A `fundamentos` é compartilhada — e é
ela que custa caro para construir. Um usuário novo não gera nenhum trabalho de ingestão.

---

## 4. MVP — o que entra na primeira versão

O produto é **uma coisa só**: *"guarde por que você comprou, e eu te aviso quando o motivo
deixar de valer."* Tudo que não serve a isso fica para depois.

| # | Tela | O que faz |
|---|---|---|
| 1 | **Entrar** | Supabase Auth (e-mail + senha, magic link) |
| 2 | **Carteira** | Adiciona posição (ticker, qtd, custo médio). Import de CSV depois. |
| 3 | **Ativo** | Preço teto (pela meta do usuário) · yield-on-cost · simulação de aporte · fundamentos da CVM · ressalvas |
| 4 | **Tese** | Escreve os pilares. **Recusa "vai subir"** e ensina o que dá para checar. Bloqueia tese que já nasce quebrada. Aposta com prazo. |
| 5 | **Painel** | Estado de todas as teses: de pé · caiu · aposta em curso · aposta perdida |
| 6 | **Alerta** | E-mail quando um pilar cai. **Só quando MUDA** — silêncio é a funcionalidade. |

### Fora do MVP (mas planejado)
Imposto (isenção de R$ 20 mil) · correlação da carteira · rebalanceamento · Telegram ·
importação de nota de corretagem · cobrança.

---

## 5. O que já existe e vai direto para o produto

Nada disso precisa ser refeito:

- **Esteira da CVM** — 4,2 M linhas, 879 empresas, 100% com data de publicação (point-in-time)
- **Os 7 bugs resolvidos** — escala das ações (Taesa reportava em milhares), plano de contas de
  banco (a conta 2.03 do Itaú é "Passivos Financeiros", não patrimônio), 1º trimestre contado
  duas vezes, dividendo a não-controlador (Vale), consolidado × individual (Sanepar),
  demonstração de empresa sem subsidiária, ISIN que não embute o ticker
- **COTAHIST** — 20 anos de B3 oficial, com ajuste de evento corporativo (o split do BBAS3
  aparecia como um "crash de −50%" fantasma)
- **Classes de ativo** (plugin): ação · FII · ETF · cripto · renda fixa
- **Motor da tese** — genérico: não sabe o que é "payout"; pergunta à classe do ativo
- **Vigia** — só avisa o que MUDA
- **O laboratório** — backtest e teste de informação. **É a prova de que a gente não mente.**

**135 testes.**

---

## 6. Ordem

| Fase | O quê |
|---|---|
| **S0** | Multi-tenant: `user_id` + RLS nas tabelas do usuário. A `fundamentos` fica pública. |
| **S1** | API FastAPI: `/ativos/{t}` · `/carteira` · `/teses` · `/checagem` |
| **S2** | Next.js + shadcn: entrar, carteira, ativo |
| **S3** | Tese (a tela que **recusa** "vai subir") e o painel |
| **S4** | Alerta por e-mail, disparado pela esteira |
| **S5** | Deploy: Vercel (front) + Fly/Railway (API) + cron da esteira |
