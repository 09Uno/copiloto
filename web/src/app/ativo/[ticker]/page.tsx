"use client";

import { use, useEffect, useState } from "react";
import { toast } from "sonner";

import { api, type Avaliacao, type Veredito, ApiError } from "@/lib/api";
import { brl, pct, corZona, rotuloZona, bordaZona } from "@/lib/formato";
import { Shell } from "@/components/shell";
import { TeseForm } from "@/components/tese-form";
import { AporteSimulador } from "@/components/aporte-simulador";
import { Glossario } from "@/components/glossario";
import { ReguaCompra } from "@/components/visuais";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export default function AtivoPage({ params }: { params: Promise<{ ticker: string }> }) {
  // Next 16: params é uma Promise — resolvida com use() no client component.
  const { ticker } = use(params);
  const tk = ticker.toUpperCase();

  const [av, setAv] = useState<Avaliacao | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  // ?editar=<id> → modo edição: busca a tese e pré-preenche o formulário.
  const [inicial, setInicial] = useState<
    {
      teseId: number;
      resumo: string;
      textos: string[];
      quali: string[];
      metaYield?: number | null;
    } | null
  >(null);

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

  useEffect(() => {
    const id = new URLSearchParams(window.location.search).get("editar");
    if (!id) return;
    api
      .get<Veredito[]>("/api/teses")
      .then((ts) => {
        const t = ts.find((x) => x.tese_id === Number(id));
        if (!t) return;
        setInicial({
          teseId: t.tese_id,
          resumo: t.resumo,
          textos: t.resultados.filter((r) => !r.qualitativo && r.texto).map((r) => r.texto!),
          quali: t.resultados.filter((r) => r.qualitativo).map((r) => r.pilar),
          metaYield: t.meta_yield,
        });
      })
      .catch(() => {});
  }, []);

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

          {/* Modo edição: mostrado no topo, e mesmo para papel sem-critério (a tese pode ser
              só qualitativa, como a da AXIA3). */}
          {inicial && (
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Editar tese</CardTitle>
                <p className="text-sm text-muted-foreground">
                  Ajuste o resumo e os pilares. Os verificáveis aparecem no modo avançado (texto).
                </p>
              </CardHeader>
              <CardContent>
                <TeseForm
                  ticker={tk}
                  metricasVerificaveis={av.metricas_verificaveis}
                  inicial={inicial}
                />
              </CardContent>
            </Card>
          )}

          {/* A classe que não tem critério ADMITE isso — não inventa um score. */}
          {av.sem_criterio ? (
            <Card>
              <CardContent className="pt-6 text-muted-foreground">{av.sem_criterio}</CardContent>
            </Card>
          ) : (
            <>
              {av.compra && (
                <Card className={bordaZona(av.compra.estado)}>
                  <CardHeader className="pb-2">
                    <CardTitle className="text-base">Preço de compra</CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-3">
                    <div className="flex items-baseline gap-2">
                      <span className="text-3xl font-semibold">{brl(av.compra.preco_compra)}</span>
                      <span className={`text-sm ${corZona(av.compra.estado)}`}>
                        {av.preco != null && rotuloZona(av.compra.estado)}
                      </span>
                    </div>

                    {/* A régua torna o critério visível: as faixas são você (teto e margem),
                        o marcador é o mercado (preço de hoje). */}
                    <div className="border-t pt-2">
                      <ReguaCompra
                        teto={av.compra.teto}
                        precoCompra={av.compra.preco_compra}
                        preco={av.preco}
                      />
                    </div>

                    {av.compra.falta_cair_pct != null && av.compra.falta_cair_pct > 0.001 && (
                      <p className="text-sm text-[var(--aposta)]">
                        falta cair {pct(av.compra.falta_cair_pct, 1)} para entrar na sua zona de
                        compra
                      </p>
                    )}

                    <p className="text-xs text-muted-foreground">
                      {av.teto?.criterio}. O preço de compra é o teto com a sua margem de
                      segurança de {pct(av.compra.margem_seguranca, 0)}. Não é previsão — o
                      critério é seu.
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

              {/* A legenda: o que cada número quer dizer e por que importa. Recolhida por
                  padrão, para quem já sabe não tropeçar nela. */}
              <Glossario
                termos={[
                  ...av.metricas.map((m) => m.nome),
                  ...Object.keys(av.metricas_verificaveis),
                ]}
              />

              {av.preco != null && <AporteSimulador ticker={tk} preco={av.preco} />}

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

              {!inicial && Object.keys(av.metricas_verificaveis).length > 0 && (
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
