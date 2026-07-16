"use client";

import { useState } from "react";
import { toast } from "sonner";

import { api, type Aporte, ApiError } from "@/lib/api";
import { brl, pct } from "@/lib/formato";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

/**
 * "Tenho R$ X. Ponho aqui?" — a pergunta que você faz todo mês, e que o teto sozinho não
 * responde. Simula o efeito de comprar N cotas AGORA sobre a SUA posição: o que acontece com o
 * seu custo médio e com o seu yield-on-cost (o dividendo sobre o preço que você pagou).
 *
 * Este endpoint já existia no backend e não tinha tela nenhuma. Não recomenda — mostra a
 * aritmética e devolve a decisão.
 */
export function AporteSimulador({ ticker, preco }: { ticker: string; preco: number }) {
  const [qtd, setQtd] = useState("");
  const [ap, setAp] = useState<Aporte | null>(null);
  const [calculando, setCalculando] = useState(false);

  async function simular(e: React.FormEvent) {
    e.preventDefault();
    const n = Number(qtd);
    if (!(n > 0)) return;
    setCalculando(true);
    try {
      const r = await api.get<Aporte | null>(`/api/ativo/${ticker}/aporte?quantidade=${n}`);
      setAp(r);
      if (!r) toast.error("não deu para simular (sem preço de mercado)");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "erro");
    } finally {
      setCalculando(false);
    }
  }

  const tomVeredito = ap?.veredito.includes("ACIMA")
    ? "text-[var(--caiu)]"
    : ap?.veredito.includes("DENTRO")
      ? "text-[var(--ok)]"
      : "text-muted-foreground";

  const desembolso = ap ? Number(qtd) * preco : 0;

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base">Simular aporte</CardTitle>
        <p className="text-sm text-muted-foreground">
          Quantas cotas você pensa em comprar hoje, a {brl(preco)}? Veja o efeito no seu custo
          médio e no seu yield-on-cost.
        </p>
      </CardHeader>
      <CardContent className="space-y-4">
        <form onSubmit={simular} className="flex items-end gap-3">
          <div className="space-y-1">
            <label className="text-xs text-muted-foreground">quantidade</label>
            <Input
              type="number"
              step="any"
              min="0"
              value={qtd}
              onChange={(e) => setQtd(e.target.value)}
              placeholder="100"
              className="w-32 font-mono"
            />
          </div>
          <Button type="submit" variant="outline" disabled={!Number(qtd) || calculando}>
            {calculando ? "…" : "Simular"}
          </Button>
          {ap && (
            <span className="text-sm text-muted-foreground ml-auto">
              desembolso <span className="font-mono text-foreground">{brl(desembolso)}</span>
            </span>
          )}
        </form>

        {ap && (
          <div className="space-y-4">
            <div className={`text-sm font-medium ${tomVeredito}`}>{ap.veredito}</div>

            <div className="grid grid-cols-2 gap-3">
              <Delta rotulo="custo médio" antes={brl(ap.custo_medio_antes)} depois={brl(ap.custo_medio_depois)} />
              <Delta
                rotulo="yield-on-cost"
                antes={ap.yoc_antes != null ? pct(ap.yoc_antes, 2) : "—"}
                depois={ap.yoc_depois != null ? pct(ap.yoc_depois, 2) : "—"}
                melhorSeMaior
              />
            </div>

            {ap.yield_atual != null && (
              <p className="text-xs text-muted-foreground">
                yield que o mercado paga hoje: <span className="font-mono">{pct(ap.yield_atual, 2)}</span>
              </p>
            )}

            {ap.motivos.length > 0 && (
              <ul className="space-y-1.5 text-sm text-muted-foreground border-t pt-3">
                {ap.motivos.map((m, i) => (
                  <li key={i}>· {m}</li>
                ))}
              </ul>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

/** antes → depois, com uma seta discreta. Não pinta de verde/vermelho: subir o custo médio não
 *  é "ruim" nem "bom" em abstrato — depende da sua tese. O número fala; a cor se cala. */
function Delta({
  rotulo,
  antes,
  depois,
  melhorSeMaior,
}: {
  rotulo: string;
  antes: string;
  depois: string;
  melhorSeMaior?: boolean;
}) {
  return (
    <div className="rounded-lg border p-3">
      <div className="text-xs text-muted-foreground">{rotulo}</div>
      <div className="flex items-baseline gap-2 font-mono tabular-nums">
        <span className="text-muted-foreground text-sm">{antes}</span>
        <span className="text-muted-foreground" aria-label="vira">
          →
        </span>
        <span className="text-lg font-semibold">{depois}</span>
      </div>
      {melhorSeMaior && (
        <div className="text-[10px] text-muted-foreground">quanto maior, melhor para você</div>
      )}
    </div>
  );
}
