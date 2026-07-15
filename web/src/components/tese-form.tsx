"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";

import { api, ApiError, type Veredito } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";

/**
 * O formulário que RECUSA "vai subir".
 *
 * Cada pilar tem de ser verificável (`payout<80%`), qualitativo (você julga) ou uma aposta
 * com prazo (`divida_ebit<5@2028-06`). A validação de verdade é da API — aqui a gente só
 * mostra a mensagem que ela devolve, que é o que ensina o usuário.
 */
export function TeseForm({
  ticker,
  metricasVerificaveis,
}: {
  ticker: string;
  metricasVerificaveis: Record<string, string>;
}) {
  const router = useRouter();
  const [resumo, setResumo] = useState("");
  const [pilares, setPilares] = useState<string[]>([""]);
  const [quali, setQuali] = useState<string[]>([]);
  const [enviando, setEnviando] = useState(false);
  const [quebrado, setQuebrado] = useState<string | null>(null);

  const metricas = Object.entries(metricasVerificaveis);

  function setPilar(i: number, v: string) {
    const novo = [...pilares];
    novo[i] = v;
    setPilares(novo);
  }

  async function criar(aceitarQuebrado?: string) {
    setEnviando(true);
    try {
      const corpo = {
        ticker,
        resumo,
        pilares: [
          ...pilares.filter((p) => p.trim()).map((texto) => ({ texto })),
          ...quali.filter((q) => q.trim()).map((qualitativo) => ({ qualitativo })),
        ],
        ...(aceitarQuebrado ? { aceitar_quebrado: aceitarQuebrado } : {}),
      };
      await api.post<Veredito>("/api/teses", corpo);
      toast.success("tese registrada");
      router.push("/");
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        // Tese que já nasce quebrada — oferece declarar como decisão consciente.
        setQuebrado(err.message);
      } else {
        toast.error(err instanceof ApiError ? err.message : "erro");
      }
    } finally {
      setEnviando(false);
    }
  }

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        criar();
      }}
      className="space-y-5"
    >
      <div className="space-y-2">
        <Label htmlFor="resumo">Por que você comprou?</Label>
        <Input
          id="resumo"
          value={resumo}
          onChange={(e) => setResumo(e.target.value)}
          placeholder="Transmissão: receita contratada e indexada ao IPCA"
          required
        />
      </div>

      <div className="space-y-2">
        <Label>Pilares verificáveis</Label>
        <p className="text-xs text-muted-foreground">
          Cada pilar é um número que dá para conferir. Ex.: <code>payout&lt;80%</code>,{" "}
          <code>roe&gt;15%</code>. Aposta em recuperação leva prazo:{" "}
          <code>divida_ebit&lt;5@2028-06</code>.
        </p>
        {pilares.map((p, i) => (
          <div key={i} className="flex gap-2">
            <Input
              value={p}
              onChange={(e) => setPilar(i, e.target.value)}
              placeholder="payout<80%"
              className="font-mono"
            />
            {i === pilares.length - 1 && (
              <Button type="button" variant="outline" onClick={() => setPilares([...pilares, ""])}>
                +
              </Button>
            )}
          </div>
        ))}

        <div className="flex flex-wrap gap-1.5 pt-1">
          <span className="text-xs text-muted-foreground mr-1">disponíveis:</span>
          {metricas.map(([nome, rotulo]) => (
            <Badge
              key={nome}
              variant="secondary"
              className="cursor-pointer font-mono text-xs"
              title={rotulo}
              onClick={() => {
                const vazio = pilares.findIndex((x) => !x.trim());
                if (vazio >= 0) setPilar(vazio, `${nome}<`);
                else setPilares([...pilares, `${nome}<`]);
              }}
            >
              {nome}
            </Badge>
          ))}
        </div>
      </div>

      <div className="space-y-2">
        <Label>Pilares que só você julga (opcional)</Label>
        <p className="text-xs text-muted-foreground">
          O que não é número — &ldquo;monopólio regulado&rdquo;, &ldquo;gestão competente&rdquo;.
          O sistema pergunta de tempos em tempos; não finge que sabe julgar.
        </p>
        {[...quali, ""].map((q, i) => (
          <Input
            key={i}
            value={q}
            onChange={(e) => {
              const novo = [...quali];
              novo[i] = e.target.value;
              setQuali(novo.filter((_, idx) => idx <= i || novo[idx]?.trim()));
            }}
            placeholder="monopólio regulado com receita contratada"
          />
        ))}
      </div>

      {quebrado && (
        <div className="rounded-md border border-[var(--caiu)]/40 bg-[var(--caiu)]/5 p-3 space-y-2 text-sm">
          <p className="text-[var(--caiu)] font-medium">Esta tese já nasce quebrada.</p>
          <p className="text-muted-foreground">{quebrado}</p>
          <p>
            Se comprar assim mesmo é uma decisão consciente, escreva o porquê — ele fica
            registrado.
          </p>
          <div className="flex gap-2">
            <Input
              placeholder="por que estou comprando mesmo assim"
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  criar((e.target as HTMLInputElement).value);
                }
              }}
            />
          </div>
        </div>
      )}

      <Button type="submit" disabled={enviando}>
        {enviando ? "…" : "Registrar tese"}
      </Button>
    </form>
  );
}
