"use client";

import Link from "next/link";

import type { FeedItem } from "@/lib/api";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

/**
 * Um card do feed: uma notícia (ou giro) resumida pela IA.
 *
 * A IA fez duas coisas, e a segunda tem uma amarra: "resumo" é o que a imprensa DIZ (factual);
 * "o que pode significar" é contexto de setor/mercado — nunca "compre/venda". Por isso o
 * bloco de significado é neutro (cinza), e não usa verde/vermelho, que neste app são estado de
 * tese, não recomendação. As fontes ficam à vista: a IA só falou do que existe.
 */
function dataCurta(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  return isNaN(d.getTime()) ? iso : d.toLocaleDateString("pt-BR");
}

export function FeedCard({ item }: { item: FeedItem }) {
  const clicavel = (item.tipo === "ativo" || item.tipo === "descoberta") && !!item.assunto;

  return (
    <Card className="gap-3 py-4">
      <CardHeader className="px-4 pb-0">
        <div className="flex flex-wrap items-center gap-2">
          {clicavel ? (
            <Link
              href={`/ativo/${item.assunto}`}
              className="font-mono font-semibold hover:underline"
            >
              {item.rotulo}
            </Link>
          ) : (
            <span className="font-semibold">{item.rotulo}</span>
          )}

          {item.tipo === "ativo" && (
            <Badge variant="secondary" className="text-[10px]">
              {item.na_carteira ? "na carteira" : "de olho"}
            </Badge>
          )}
          {item.tipo === "descoberta" && (
            <Badge variant="outline" className="text-[10px]">
              descoberta
            </Badge>
          )}
          {item.tipo === "macro" && (
            <Badge variant="outline" className="text-[10px]">
              macro
            </Badge>
          )}

          {item.data && (
            <span className="ml-auto text-[11px] text-muted-foreground/70">
              {dataCurta(item.data)}
            </span>
          )}
        </div>
        {item.titulo && <p className="mt-1 text-sm font-medium">{item.titulo}</p>}
      </CardHeader>

      <CardContent className="space-y-2 px-4">
        {item.resumo && (
          <p className="text-sm leading-snug text-foreground/90">{item.resumo}</p>
        )}

        {item.mercado && (
          <p className="rounded-md bg-secondary/40 px-3 py-2 text-sm leading-snug">
            <span className="text-muted-foreground">O que pode significar pro mercado: </span>
            {item.mercado}
          </p>
        )}

        {item.fontes.length > 0 && (
          <div className="flex flex-wrap gap-x-3 gap-y-1 pt-0.5">
            {item.fontes.map((f, i) => (
              <a
                key={i}
                href={f.url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-[11px] text-muted-foreground underline decoration-dotted underline-offset-2 hover:text-foreground"
              >
                {f.fonte || "fonte"}
                {f.data ? ` · ${dataCurta(f.data)}` : ""}
              </a>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
