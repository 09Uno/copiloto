"use client";

import { use, useEffect, useState } from "react";
import { toast } from "sonner";

import { api, type Avaliacao, ApiError } from "@/lib/api";
import { brl, pct } from "@/lib/formato";
import { Shell } from "@/components/shell";
import { TeseForm } from "@/components/tese-form";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export default function AtivoPage({ params }: { params: Promise<{ ticker: string }> }) {
  // Next 16: params é uma Promise — resolvida com use() no client component.
  const { ticker } = use(params);
  const tk = ticker.toUpperCase();

  const [av, setAv] = useState<Avaliacao | null>(null);
  const [erro, setErro] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<Avaliacao>(`/api/ativo/${tk}`)
      .then(setAv)
      .catch((e) => {
        if (e instanceof ApiError && e.status !== 401) {
          setErro(e.message);
          toast.error(e.message);
        }
      });
  }, [tk]);

  return (
    <Shell>
      {av === null ? (
        <p className="text-muted-foreground text-sm">{erro ?? "carregando…"}</p>
      ) : (
        <div className="space-y-6">
          <div className="flex items-baseline gap-3">
            <h1 className="text-2xl font-semibold">{av.ticker}</h1>
            <span className="text-muted-foreground">{av.classe}</span>
            {av.preco != null && <span className="ml-auto text-xl">{brl(av.preco)}</span>}
          </div>

          {/* A classe que não tem critério ADMITE isso — não inventa um score. */}
          {av.sem_criterio ? (
            <Card>
              <CardContent className="pt-6 text-muted-foreground">{av.sem_criterio}</CardContent>
            </Card>
          ) : (
            <>
              {av.teto && (
                <Card className={av.teto.abaixo ? "border-[var(--ok)]/40" : "border-[var(--caiu)]/40"}>
                  <CardHeader className="pb-2">
                    <CardTitle className="text-base">Preço teto</CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-1">
                    <div className="flex items-baseline gap-2">
                      <span className="text-2xl font-semibold">{brl(av.teto.valor)}</span>
                      <span
                        className={`text-sm ${av.teto.abaixo ? "text-[var(--ok)]" : "text-[var(--caiu)]"}`}
                      >
                        {av.teto.abaixo ? "abaixo do teto" : "acima do teto"}
                        {av.teto.margem_pct != null &&
                          ` (${av.teto.margem_pct > 0 ? "+" : ""}${av.teto.margem_pct.toFixed(1)}%)`}
                      </span>
                    </div>
                    <p className="text-xs text-muted-foreground">{av.teto.criterio}</p>
                    <p className="text-xs text-muted-foreground pt-1">
                      É o preço em que o dividendo entrega a sua meta de yield. Não é previsão —
                      o critério é seu.
                    </p>
                  </CardContent>
                </Card>
              )}

              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-base">Fundamentos (CVM)</CardTitle>
                </CardHeader>
                <CardContent>
                  <dl className="grid grid-cols-2 sm:grid-cols-3 gap-x-6 gap-y-2 text-sm">
                    {av.metricas.map((m) => (
                      <div key={m.nome} className="flex justify-between border-b border-border/50 py-1">
                        <dt className="text-muted-foreground">{m.rotulo}</dt>
                        <dd className="font-mono">{m.texto}</dd>
                      </div>
                    ))}
                  </dl>
                </CardContent>
              </Card>

              {av.alertas.length > 0 && (
                <Card>
                  <CardHeader className="pb-2">
                    <CardTitle className="text-base text-[var(--aposta)]">Ressalvas</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <ul className="space-y-1.5 text-sm text-muted-foreground">
                      {av.alertas.map((a, i) => (
                        <li key={i}>· {a}</li>
                      ))}
                    </ul>
                  </CardContent>
                </Card>
              )}

              {Object.keys(av.metricas_verificaveis).length > 0 && (
                <Card>
                  <CardHeader>
                    <CardTitle className="text-base">Registrar tese</CardTitle>
                    <p className="text-sm text-muted-foreground">
                      Escreva por que comprou. O sistema avisa quando o motivo deixar de valer.
                    </p>
                  </CardHeader>
                  <CardContent>
                    <TeseForm ticker={tk} metricasVerificaveis={av.metricas_verificaveis} />
                  </CardContent>
                </Card>
              )}
            </>
          )}
        </div>
      )}
    </Shell>
  );
}
