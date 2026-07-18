"use client";

import type { Veredito } from "@/lib/api";
import { pct, corEstado, iconeEstado, corZona, rotuloZona } from "@/lib/formato";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ReguaCompra } from "@/components/visuais";
import { ContextoPilar } from "@/components/contexto-pilar";
import Link from "next/link";

/** Uma tese e o estado dos seus pilares. O sistema nunca diz "venda" — devolve a pergunta.
 *  Se receber `onEncerrar`, mostra a ação de arquivar a tese (com o motivo — encerrar sem
 *  dizer por quê apaga o aprendizado). */
export function VeredictoCard({
  v,
  onEncerrar,
}: {
  v: Veredito;
  onEncerrar?: (v: Veredito) => void;
}) {
  const temProblema = v.resultados.some((r) => r.estado === "CAIU" || r.estado === "PERDEU");
  // Para o que você só acompanha, o sinal que interessa é o preço entrar na zona com pilares de pé.
  const oportunidade = !v.tenho && !temProblema && v.compra?.estado === "COMPRA";

  return (
    <Card
      className={
        oportunidade
          ? "border-[var(--ok)]/50"
          : temProblema
            ? "border-[var(--caiu)]/40"
            : undefined
      }
    >
      <CardHeader className="pb-3">
        <div className="flex items-baseline justify-between gap-3">
          <div className="flex items-center gap-2">
            <Link href={`/ativo/${v.ticker}`} className="font-semibold hover:underline">
              {v.ticker}
            </Link>
            <Badge variant={v.tenho ? "secondary" : "outline"} className="text-xs">
              {v.tenho ? "na carteira" : "de olho"}
            </Badge>
          </div>
          <span className={`text-sm ${temProblema ? "text-[var(--caiu)]" : "text-[var(--ok)]"}`}>
            {v.de_pe}/{v.total_verificaveis} pilares de pé
          </span>
        </div>
        <p className="text-sm text-muted-foreground">{v.resumo}</p>
      </CardHeader>
      <CardContent className="space-y-2">
        {/* Zona de compra: fato contra o SEU critério, não recomendação. A régua torna o
            critério visível — as faixas são você, o marcador é o mercado. */}
        {v.compra && (
          <div className="rounded-md bg-muted/40 px-3 py-2">
            <div className="flex items-baseline justify-between gap-2 text-sm">
              <span className="text-muted-foreground">zona de compra</span>
              <span className={corZona(v.compra.estado)}>
                {v.compra.estado === "COMPRA"
                  ? "na zona"
                  : v.compra.falta_cair_pct != null && v.compra.falta_cair_pct > 0
                    ? `falta −${pct(v.compra.falta_cair_pct, 0)}`
                    : rotuloZona(v.compra.estado)}
              </span>
            </div>
            <ReguaCompra
              teto={v.compra.teto}
              precoCompra={v.compra.preco_compra}
              preco={v.preco}
            />
          </div>
        )}

        <ul className="space-y-1.5">
          {v.resultados.map((r, i) => (
            <li key={i} className="text-sm flex gap-2">
              <span className={corEstado(r.estado)}>{iconeEstado(r.estado)}</span>
              <span className="flex-1">
                <span className="font-mono">{r.pilar}</span>
                {r.motivo && (
                  <span className="block text-xs text-muted-foreground">{r.motivo}</span>
                )}
                {r.qualitativo && r.pilar_id != null && (
                  <ContextoPilar pilarId={r.pilar_id} inicial={r.contexto} />
                )}
              </span>
            </li>
          ))}
        </ul>
        <div className="pt-2 border-t space-y-2">
          <p className="text-sm italic text-muted-foreground">{v.pergunta}</p>
          <div className="flex gap-4">
            <Link
              href={`/ativo/${v.ticker}?editar=${v.tese_id}`}
              className="text-xs text-muted-foreground hover:text-foreground"
            >
              editar
            </Link>
            {onEncerrar && (
              <button
                type="button"
                onClick={() => onEncerrar(v)}
                className="text-xs text-muted-foreground hover:text-[var(--caiu)]"
              >
                encerrar tese
              </button>
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
