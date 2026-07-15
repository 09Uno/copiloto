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
