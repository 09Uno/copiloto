// Formatação BR — reais e percentuais.

export const brl = (v: number) =>
  v.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });

export const pct = (v: number, casas = 1) =>
  `${(v * 100).toLocaleString("pt-BR", { minimumFractionDigits: casas, maximumFractionDigits: casas })}%`;

// Cor de ESTADO da tese — nunca de recomendação. Verde = pilar de pé, vermelho = caiu,
// âmbar = aposta em curso, cinza = a verificar / qualitativo.
export function corEstado(estado: string): string {
  switch (estado) {
    case "OK":
      return "text-[var(--ok)]";
    case "CAIU":
    case "PERDEU":
      return "text-[var(--caiu)]";
    case "APOSTANDO":
      return "text-[var(--aposta)]";
    default:
      return "text-muted-foreground";
  }
}

export function iconeEstado(estado: string): string {
  return (
    { OK: "✓", CAIU: "✗", APOSTANDO: "⏳", PERDEU: "💀", PERGUNTAR: "?", "?": "—" } as Record<
      string,
      string
    >
  )[estado] ?? "•";
}

// --- Zona de compra. NÃO é "compre/venda" — é onde o preço está frente ao SEU critério
// (sua meta de yield gera o teto; sua margem gera o preço de compra). Verde = na sua zona,
// âmbar = serve mas sem margem, cinza = caro para a sua meta.
export function corZona(estado: string): string {
  switch (estado) {
    case "COMPRA":
      return "text-[var(--ok)]";
    case "JUSTO":
      return "text-[var(--aposta)]";
    default: // CARO
      return "text-muted-foreground";
  }
}

export function rotuloZona(estado: string): string {
  return (
    { COMPRA: "na sua zona de compra", JUSTO: "abaixo do teto, sem margem", CARO: "acima do teto" } as Record<
      string,
      string
    >
  )[estado] ?? estado;
}

export function bordaZona(estado: string): string {
  switch (estado) {
    case "COMPRA":
      return "border-[var(--ok)]/40";
    case "JUSTO":
      return "border-[var(--aposta)]/40";
    default:
      return "border-[var(--caiu)]/30";
  }
}
