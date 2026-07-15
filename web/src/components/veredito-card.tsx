"use client";

import type { Veredito } from "@/lib/api";
import { corEstado, iconeEstado } from "@/lib/formato";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import Link from "next/link";

/** Uma tese e o estado dos seus pilares. O sistema nunca diz "venda" — devolve a pergunta. */
export function VeredictoCard({ v }: { v: Veredito }) {
  const temProblema = v.resultados.some((r) => r.estado === "CAIU" || r.estado === "PERDEU");

  return (
    <Card className={temProblema ? "border-[var(--caiu)]/40" : undefined}>
      <CardHeader className="pb-3">
        <div className="flex items-baseline justify-between gap-3">
          <Link href={`/ativo/${v.ticker}`} className="font-semibold hover:underline">
            {v.ticker}
          </Link>
          <span className={`text-sm ${temProblema ? "text-[var(--caiu)]" : "text-[var(--ok)]"}`}>
            {v.de_pe}/{v.total_verificaveis} pilares de pé
          </span>
        </div>
        <p className="text-sm text-muted-foreground">{v.resumo}</p>
      </CardHeader>
      <CardContent className="space-y-2">
        <ul className="space-y-1.5">
          {v.resultados.map((r, i) => (
            <li key={i} className="text-sm flex gap-2">
              <span className={corEstado(r.estado)}>{iconeEstado(r.estado)}</span>
              <span className="flex-1">
                <span className="font-mono">{r.pilar}</span>
                {r.motivo && (
                  <span className="block text-xs text-muted-foreground">{r.motivo}</span>
                )}
              </span>
            </li>
          ))}
        </ul>
        <p className="text-sm italic text-muted-foreground pt-2 border-t">{v.pergunta}</p>
      </CardContent>
    </Card>
  );
}
