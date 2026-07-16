// Primitivas visuais do painel. Nada aqui recomenda nada: são ENCODINGS.
//
//  · ReguaCompra  — posição do preço de hoje entre a sua zona de compra, o teto e o "caro".
//  · StatTile     — um número de manchete (quantos pilares caíram, quantas oportunidades).
//  · Alocacao     — barras de magnitude (quanto cada ativo pesa na carteira). Nunca pizza.
//  · SeloTese     — pílula de ESTADO da tese, sempre com ícone + rótulo (nunca cor sozinha).
//  · Pilares      — pips compactos "N de M de pé".
//
// Cor segue a regra do design: verde/vermelho/âmbar = status (reservado); azul = dado
// (magnitude). Texto sempre em tinta neutra; a cor mora na marca ao lado, não no número.

import Link from "next/link";
import { brl } from "@/lib/formato";

// ----------------------------------------------------------------- ReguaCompra

/** Onde o preço de hoje caiu na sua régua: |—— zona de compra ——|— sem margem —|— caro —|
 *  A régua é o SEU critério tornado visível: o teto sai da sua meta de yield, o preço de
 *  compra é o teto menos a sua margem. O marcador é o mercado; as faixas são você. */
export function ReguaCompra({
  teto,
  precoCompra,
  preco,
}: {
  teto: number;
  precoCompra: number;
  preco: number | null;
}) {
  // Eixo com folga dos dois lados para os extremos não colarem na borda.
  const pontos = [precoCompra, teto, ...(preco != null ? [preco] : [])];
  const min = Math.min(...pontos) * 0.96;
  const max = Math.max(...pontos) * 1.04;
  const span = max - min || 1;
  const frac = (v: number) => Math.max(0, Math.min(1, (v - min) / span));

  const wCompra = frac(precoCompra) * 100; // zona de compra: início → preço de compra
  const wJusto = (frac(teto) - frac(precoCompra)) * 100; // sem margem: compra → teto
  const wCaro = 100 - frac(teto) * 100; // caro: teto → fim
  const posHoje = preco != null ? frac(preco) * 100 : null;

  return (
    <div className="pt-5 pb-6">
      <div className="relative">
        {/* marcador do preço de hoje, acima da trilha */}
        {posHoje != null && preco != null && (
          <div
            className="absolute -top-5 -translate-x-1/2 flex flex-col items-center"
            style={{ left: `${posHoje}%` }}
          >
            <span className="text-[11px] font-mono font-medium whitespace-nowrap">
              {brl(preco)}
            </span>
            <span className="text-muted-foreground text-[9px] -mt-0.5">hoje</span>
          </div>
        )}

        {/* trilha: três faixas com 2px de respiro entre elas */}
        <div className="flex h-2 gap-0.5">
          <div
            className="rounded-full bg-[var(--ok)]/35"
            style={{ width: `${wCompra}%` }}
            title="sua zona de compra"
          />
          <div
            className="rounded-full bg-[var(--aposta)]/35"
            style={{ width: `${wJusto}%` }}
            title="abaixo do teto, sem margem"
          />
          <div
            className="rounded-full bg-[var(--caiu)]/25"
            style={{ width: `${wCaro}%` }}
            title="acima do teto"
          />
        </div>

        {/* agulha do preço de hoje sobre a trilha */}
        {posHoje != null && (
          <div
            className="absolute top-0 h-2 w-0.5 -translate-x-1/2 rounded-full bg-foreground ring-2 ring-background"
            style={{ left: `${posHoje}%` }}
          />
        )}

        {/* marcos: preço de compra e teto, ancorados na trilha */}
        <div
          className="absolute top-2.5 -translate-x-1/2 text-center"
          style={{ left: `${frac(precoCompra) * 100}%` }}
        >
          <div className="text-[10px] text-muted-foreground">compra</div>
          <div className="text-[11px] font-mono">{brl(precoCompra)}</div>
        </div>
        <div
          className="absolute top-2.5 -translate-x-1/2 text-center"
          style={{ left: `${frac(teto) * 100}%` }}
        >
          <div className="text-[10px] text-muted-foreground">teto</div>
          <div className="text-[11px] font-mono">{brl(teto)}</div>
        </div>
      </div>
    </div>
  );
}

// -------------------------------------------------------------------- StatTile

type Tom = "ok" | "caiu" | "aposta" | "dado" | "neutro";

const CORES_TOM: Record<Tom, string> = {
  ok: "text-[var(--ok)]",
  caiu: "text-[var(--caiu)]",
  aposta: "text-[var(--aposta)]",
  dado: "text-[var(--dado)]",
  neutro: "text-foreground",
};

/** Um número de manchete com rótulo. Vira link se receber `href` — para o número ser
 *  também a porta para a lista que ele resume. */
export function StatTile({
  rotulo,
  valor,
  sub,
  tom = "neutro",
  href,
}: {
  rotulo: string;
  valor: React.ReactNode;
  sub?: string;
  tom?: Tom;
  href?: string;
}) {
  const conteudo = (
    <>
      <div className="text-xs text-muted-foreground uppercase tracking-wide">{rotulo}</div>
      <div className={`text-3xl font-semibold tabular-nums ${CORES_TOM[tom]}`}>{valor}</div>
      {sub && <div className="text-xs text-muted-foreground">{sub}</div>}
    </>
  );
  const classe =
    "flex flex-col gap-1 rounded-xl border bg-card p-4 shadow-sm transition-colors";
  return href ? (
    <Link href={href} className={`${classe} hover:border-foreground/25`}>
      {conteudo}
    </Link>
  ) : (
    <div className={classe}>{conteudo}</div>
  );
}

// -------------------------------------------------------------------- Alocacao

/** Barras de magnitude: quanto cada ativo pesa na carteira. Ordenadas do maior ao menor,
 *  uma cor só (dado, não status). Acima de `limite` itens, o resto colapsa em "+N outros" —
 *  explícito, nunca truncado em silêncio. */
export function Alocacao({
  itens,
  limite = 8,
}: {
  itens: { rotulo: string; valor: number; href?: string }[];
  limite?: number;
}) {
  const total = itens.reduce((s, i) => s + i.valor, 0) || 1;
  const ordenados = [...itens].sort((a, b) => b.valor - a.valor);
  const topo = ordenados.slice(0, limite);
  const resto = ordenados.slice(limite);
  const restoValor = resto.reduce((s, i) => s + i.valor, 0);

  const linha = (rotulo: string, valor: number, href?: string, key?: string) => {
    const pct = (valor / total) * 100;
    const nome = href ? (
      <Link href={href} className="font-mono hover:underline">
        {rotulo}
      </Link>
    ) : (
      <span className="font-mono text-muted-foreground">{rotulo}</span>
    );
    return (
      <div key={key ?? rotulo} className="grid grid-cols-[4.5rem_1fr_auto] items-center gap-3">
        <div className="text-sm truncate">{nome}</div>
        <div className="h-2.5 rounded-full bg-muted/60">
          <div
            className="h-full rounded-full bg-[var(--dado)]/80"
            style={{ width: `${Math.max(pct, 1.5)}%` }}
          />
        </div>
        <div className="text-xs font-mono text-muted-foreground tabular-nums w-20 text-right">
          {brl(valor)} · {pct.toFixed(0)}%
        </div>
      </div>
    );
  };

  return (
    <div className="space-y-2">
      {topo.map((i) => linha(i.rotulo, i.valor, i.href))}
      {resto.length > 0 && linha(`+${resto.length} outros`, restoValor, undefined, "__resto")}
    </div>
  );
}

// -------------------------------------------------------------------- SeloTese

export type EstadoTese = "de_pe" | "caiu" | "aposta" | "sem_tese";

const SELO: Record<EstadoTese, { icone: string; texto: string; classe: string }> = {
  de_pe: { icone: "✓", texto: "tese de pé", classe: "text-[var(--ok)] border-[var(--ok)]/40" },
  caiu: { icone: "✗", texto: "pilar caiu", classe: "text-[var(--caiu)] border-[var(--caiu)]/40" },
  aposta: {
    icone: "⏳",
    texto: "aposta em curso",
    classe: "text-[var(--aposta)] border-[var(--aposta)]/40",
  },
  sem_tese: {
    icone: "○",
    texto: "sem tese",
    classe: "text-muted-foreground border-dashed border-border",
  },
};

/** Pílula de estado da tese — SEMPRE ícone + rótulo, para a informação não morar só na cor. */
export function SeloTese({ estado }: { estado: EstadoTese }) {
  const s = SELO[estado];
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium ${s.classe}`}
    >
      <span aria-hidden>{s.icone}</span>
      {s.texto}
    </span>
  );
}

// --------------------------------------------------------------------- Pilares

/** Pips compactos: N de M pilares de pé. Um traço por pilar — verde de pé, vermelho caído. */
export function Pilares({
  dePe,
  total,
  comProblema = false,
}: {
  dePe: number;
  total: number;
  comProblema?: boolean;
}) {
  if (total === 0) return <span className="text-xs text-muted-foreground">—</span>;
  return (
    <span className="inline-flex items-center gap-2">
      <span className="flex gap-0.5" aria-hidden>
        {Array.from({ length: total }).map((_, i) => (
          <span
            key={i}
            className={`h-1.5 w-3 rounded-full ${
              i < dePe && !comProblema
                ? "bg-[var(--ok)]"
                : i < dePe
                  ? "bg-[var(--ok)]/70"
                  : "bg-[var(--caiu)]"
            }`}
          />
        ))}
      </span>
      <span className={`text-xs tabular-nums ${comProblema ? "text-[var(--caiu)]" : "text-muted-foreground"}`}>
        {dePe}/{total}
      </span>
    </span>
  );
}
