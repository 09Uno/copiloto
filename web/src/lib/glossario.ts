// A legenda dos termos. Fonte única da verdade: as chaves batem com as métricas que o backend
// expõe (app/ativos/acao.py e fii.py — `metricas_disponiveis`). Cada verbete diz o que é e,
// principalmente, POR QUE importa — porque um número que você não entende não vira decisão.

export type Termo = {
  rotulo: string;
  oquee: string;
  porque: string;
  direcao?: "alto" | "baixo"; // qual lado costuma ser melhor (só quando é claro)
};

export const GLOSSARIO: Record<string, Termo> = {
  // ---- ações
  lpa: {
    rotulo: "LPA — Lucro por ação",
    oquee: "o lucro do ano dividido pelo número de ações.",
    porque: "é a base do P/L e mostra quanto a empresa gera para cada ação que você tem.",
  },
  vpa: {
    rotulo: "VPA — Valor patrimonial por ação",
    oquee: "o patrimônio líquido dividido pelo número de ações — o valor contábil de cada ação.",
    porque: "é a base do P/VP; comparado ao preço, diz se você paga acima ou abaixo do patrimônio.",
  },
  dpa: {
    rotulo: "DPA — Dividendo/rendimento por ação (12m)",
    oquee: "quanto a empresa (ou o FII) pagou de provento por ação nos últimos 12 meses.",
    porque:
      "é o dinheiro que de fato cai na sua conta — o numerador do dividend yield e do seu yield-on-cost.",
    direcao: "alto",
  },
  roe: {
    rotulo: "ROE — Retorno sobre o patrimônio",
    oquee: "o lucro dividido pelo patrimônio líquido: quanto a empresa gera sobre o capital dos sócios.",
    porque: "ROE alto e constante é sinal de negócio que reinveste bem. É qualidade, não preço.",
    direcao: "alto",
  },
  cresc_lucro: {
    rotulo: "Crescimento do lucro",
    oquee: "a variação do lucro dos últimos 12 meses contra os 12 anteriores.",
    porque: "“a empresa cresce” é o motivo de compra mais comum e o menos verificado — aqui vira número.",
    direcao: "alto",
  },
  cresc_receita: {
    rotulo: "Crescimento da receita",
    oquee: "a mesma comparação, mas para a receita (o faturamento).",
    porque: "receita sustenta o lucro no longo prazo; receita caindo é a tese começando a furar.",
    direcao: "alto",
  },
  payout: {
    rotulo: "Payout",
    oquee: "a fatia do lucro que a empresa distribui como provento.",
    porque:
      "payout muito alto (perto ou acima de 100%) costuma ser dividendo insustentável — pago com dívida ou caixa, não com lucro.",
  },
  divida_ebit: {
    rotulo: "Dív. líquida / EBIT",
    oquee: "quantos anos do resultado operacional (EBIT) pagariam a dívida líquida.",
    porque:
      "alavancagem é o que quebra empresa boa quando o juro sobe. Acima de ~3x já pede atenção; é o freio de mão da tese.",
    direcao: "baixo",
  },
  margem: {
    rotulo: "Margem líquida",
    oquee: "quanto de cada real de faturamento sobra como lucro.",
    porque: "margem alta e estável indica poder de preço e eficiência; margem espremendo é sinal de aperto.",
    direcao: "alto",
  },
  pl: {
    rotulo: "P/L — Preço / Lucro",
    oquee: "quantos anos de lucro atual você paga no preço de hoje.",
    porque:
      "é o termômetro de “caro ou barato” mais usado. Baixo pode ser barganha — ou armadilha, se o lucro vai cair.",
    direcao: "baixo",
  },
  pvp: {
    rotulo: "P/VP — Preço / Valor patrimonial",
    oquee: "quantas vezes o valor contábil (patrimônio) você paga pela ação.",
    porque:
      "referência clássica de preço para bancos e seguradoras. Abaixo de 1 é pagar menos que o patrimônio — nem sempre uma pechincha.",
    direcao: "baixo",
  },
  p_vp: {
    rotulo: "P/VP — Preço / Valor patrimonial da cota",
    oquee: "quantas vezes o valor patrimonial da cota você paga pelo FII.",
    porque:
      "em FII, P/VP abaixo de 1 é comprar a cota por menos que o patrimônio do fundo. Acima de 1, ágio — vale se a gestão justifica.",
    direcao: "baixo",
  },
  dy: {
    rotulo: "DY — Dividend yield",
    oquee: "o provento dos últimos 12 meses dividido pelo preço de hoje.",
    porque:
      "é o que um aporte HOJE renderia. A sua meta de yield (e o teto que sai dela) é medida contra este número.",
    direcao: "alto",
  },
  pl_vs_historia: {
    rotulo: "P/L vs. a própria história",
    oquee: "o P/L de hoje comparado à mediana histórica do próprio papel.",
    porque:
      "separa “barato de verdade” de “sempre foi assim”. Acima de 100% é o papel mais caro que o seu normal — é euforia virando número.",
  },
  pvp_vs_historia: {
    rotulo: "P/VP vs. a própria história",
    oquee: "o P/VP de hoje comparado à mediana histórica do próprio papel.",
    porque: "mesmo raciocínio do P/L vs. história: caro ou barato em relação a ele mesmo, não ao mercado.",
  },
  // ---- FIIs
  alavancagem: {
    rotulo: "Alavancagem — Passivo / PL",
    oquee: "quanto o fundo deve em relação ao próprio patrimônio.",
    porque: "FII muito alavancado sofre mais quando o juro sobe. É risco escondido atrás de um yield bonito.",
    direcao: "baixo",
  },
  cotistas: {
    rotulo: "Cotistas",
    oquee: "quantos investidores dividem o fundo.",
    porque: "muitos cotistas costuma significar mais liquidez e menos risco de um grande girar o preço sozinho.",
    direcao: "alto",
  },
  patrimonio: {
    rotulo: "Patrimônio líquido",
    oquee: "o tamanho do fundo.",
    porque: "fundos maiores tendem a ter mais liquidez e a diluir melhor os custos fixos.",
  },
  perfil: {
    rotulo: "Perfil — tijolo / papel / híbrido",
    oquee: "se o FII tem imóvel físico (tijolo), recebíveis como CRI (papel), ou os dois.",
    porque:
      "muda tudo: tijolo vive de aluguel e vacância; papel, de juro e crédito. Comparar um com o outro é laranja com maçã.",
  },
};

/** Verbetes para uma lista de chaves, sem repetir o mesmo rótulo (P/VP de ação e FII coincidem)
 *  e na ordem em que aparecem. Chave desconhecida é ignorada. */
export function verbetes(chaves: string[]): [string, Termo][] {
  const vistos = new Set<string>();
  const out: [string, Termo][] = [];
  for (const c of chaves) {
    const t = GLOSSARIO[c];
    if (!t || vistos.has(t.rotulo)) continue;
    vistos.add(t.rotulo);
    out.push([c, t]);
  }
  return out;
}
