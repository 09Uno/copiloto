"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";

import { api, ApiError, type Veredito } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Glossario, ExplicaTermo } from "@/components/glossario";

/**
 * O formulário que RECUSA "vai subir".
 *
 * Antes era só um campo de texto cru (`payout<80%`) — potente, mas críptico. Agora o caminho
 * padrão é guiado: escolha a métrica, o operador e o valor, e o sistema monta o pilar para
 * você, mostrando ao vivo o que vai gravar. O modo avançado (texto cru, apostas com prazo em
 * uma linha) continua ali para quem já sabe. A validação de verdade é da API — aqui a gente só
 * mostra a mensagem que ela devolve, que é o que ensina.
 */

type Guiado = {
  metrica: string;
  op: string;
  valor: string;
  unidade: "%" | "×";
  aposta: boolean;
  prazo: string; // AAAA-MM
};

const guiadoVazio = (metrica = ""): Guiado => ({
  metrica,
  op: "<",
  valor: "",
  unidade: "%",
  aposta: false,
  prazo: "",
});

/** Monta o texto que a API espera a partir das partes escolhidas. `null` se incompleto. */
function textoDoGuiado(g: Guiado): string | null {
  if (!g.metrica || !g.valor.trim()) return null;
  let s = `${g.metrica}${g.op}${g.valor.trim()}${g.unidade === "%" ? "%" : ""}`;
  if (g.aposta && g.prazo) s += `@${g.prazo}`;
  return s;
}

export function TeseForm({
  ticker,
  metricasVerificaveis,
  inicial,
}: {
  ticker: string;
  metricasVerificaveis: Record<string, string>;
  // presente = modo EDIÇÃO: pré-preenche e salva com PUT. Os pilares verificáveis vêm no formato
  // cru ("roe>0.25") no modo avançado — inequívoco, sem o vaivém de %/× do formulário guiado.
  // metaYield: a meta de yield gravada nesta tese (fração, ex.: 0.08) — pré-preenche o preço-alvo.
  inicial?: {
    teseId: number;
    resumo: string;
    textos: string[];
    quali: string[];
    metaYield?: number | null;
  };
}) {
  const router = useRouter();
  const metricas = Object.entries(metricasVerificaveis);
  const editando = !!inicial;

  const [resumo, setResumo] = useState(inicial?.resumo ?? "");
  const [guiados, setGuiados] = useState<Guiado[]>(
    editando ? [] : [guiadoVazio(metricas[0]?.[0] ?? "")],
  );
  const [quali, setQuali] = useState<string[]>(inicial?.quali ?? []);
  const [avancado, setAvancado] = useState(editando);
  const [crus, setCrus] = useState<string[]>(inicial?.textos?.length ? inicial.textos : [""]);
  // Meta de yield SÓ desta tese, guardada em % (vazio = usa a meta padrão da classe).
  const [metaPct, setMetaPct] = useState(
    inicial?.metaYield != null ? (inicial.metaYield * 100).toString() : "",
  );
  const [enviando, setEnviando] = useState(false);
  const [quebrado, setQuebrado] = useState<string | null>(null);

  function setGuiado(i: number, patch: Partial<Guiado>) {
    setGuiados((gs) => gs.map((g, idx) => (idx === i ? { ...g, ...patch } : g)));
  }

  async function criar(aceitarQuebrado?: string) {
    setEnviando(true);
    try {
      const textos = [
        ...guiados.map(textoDoGuiado).filter((t): t is string => !!t),
        ...(avancado ? crus.filter((c) => c.trim()) : []),
      ];
      // Meta em fração (0.08). Vazio → omite → a API usa a meta padrão da classe.
      const metaNum = Number(metaPct.trim().replace(",", "."));
      const corpo = {
        ticker,
        resumo,
        pilares: [
          ...textos.map((texto) => ({ texto })),
          ...quali.filter((q) => q.trim()).map((qualitativo) => ({ qualitativo })),
        ],
        ...(metaPct.trim() && metaNum > 0 ? { meta_yield: metaNum / 100 } : {}),
        ...(aceitarQuebrado ? { aceitar_quebrado: aceitarQuebrado } : {}),
      };
      if (editando) {
        await api.put<Veredito>(`/api/teses/${inicial!.teseId}`, corpo);
        toast.success("tese atualizada");
      } else {
        await api.post<Veredito>("/api/teses", corpo);
        toast.success("tese registrada");
      }
      router.push("/");
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
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

      <div className="space-y-3">
        <div>
          <Label>Pilares verificáveis</Label>
          <p className="text-xs text-muted-foreground">
            Cada pilar é um número que dá para conferir. Monte abaixo — o sistema avisa quando
            deixar de valer.
          </p>
        </div>

        {guiados.map((g, i) => {
          const preview = textoDoGuiado(g);
          return (
            <div key={i} className="rounded-lg border p-3 space-y-2">
              <div className="flex flex-wrap items-center gap-2">
                <select
                  value={g.metrica}
                  onChange={(e) => setGuiado(i, { metrica: e.target.value })}
                  className="h-9 rounded-md border bg-transparent px-2 text-sm font-mono min-w-32"
                >
                  {metricas.length === 0 && <option value="">—</option>}
                  {metricas.map(([nome, rotulo]) => (
                    <option key={nome} value={nome} title={rotulo}>
                      {nome}
                    </option>
                  ))}
                </select>

                <select
                  value={g.op}
                  onChange={(e) => setGuiado(i, { op: e.target.value })}
                  className="h-9 rounded-md border bg-transparent px-2 text-sm font-mono"
                  aria-label="operador"
                >
                  <option value="<">{"< menor que"}</option>
                  <option value="<=">{"≤ até"}</option>
                  <option value=">">{"> maior que"}</option>
                  <option value=">=">{"≥ pelo menos"}</option>
                </select>

                <Input
                  value={g.valor}
                  onChange={(e) => setGuiado(i, { valor: e.target.value })}
                  placeholder="80"
                  inputMode="decimal"
                  className="w-24 font-mono"
                />

                <div className="inline-flex rounded-md border overflow-hidden">
                  {(["%", "×"] as const).map((u) => (
                    <button
                      key={u}
                      type="button"
                      onClick={() => setGuiado(i, { unidade: u })}
                      className={`px-2.5 h-9 text-sm ${
                        g.unidade === u
                          ? "bg-secondary text-secondary-foreground"
                          : "text-muted-foreground hover:text-foreground"
                      }`}
                      title={u === "%" ? "percentual (payout, roe…)" : "múltiplo / número (p_vp, dívida/ebit…)"}
                    >
                      {u}
                    </button>
                  ))}
                </div>

                {guiados.length > 1 && (
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon-sm"
                    className="text-muted-foreground"
                    onClick={() => setGuiados((gs) => gs.filter((_, idx) => idx !== i))}
                    title="remover pilar"
                  >
                    ✕
                  </Button>
                )}
              </div>

              <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
                <label className="flex items-center gap-1.5 text-xs text-muted-foreground cursor-pointer">
                  <input
                    type="checkbox"
                    checked={g.aposta}
                    onChange={(e) => setGuiado(i, { aposta: e.target.checked })}
                    className="size-3.5 accent-[var(--aposta)]"
                  />
                  é uma aposta com prazo
                </label>
                {g.aposta && (
                  <input
                    type="month"
                    value={g.prazo}
                    onChange={(e) => setGuiado(i, { prazo: e.target.value })}
                    className="h-8 rounded-md border bg-transparent px-2 text-xs font-mono"
                    title="até quando você dá para essa aposta se provar"
                  />
                )}
                {preview && (
                  <span className="ml-auto text-xs text-muted-foreground">
                    vira <code className="font-mono text-foreground">{preview}</code>
                  </span>
                )}
              </div>

              {/* o que é a métrica que ele acabou de escolher, e por que importa */}
              {g.metrica && <ExplicaTermo chave={g.metrica} />}
            </div>
          );
        })}

        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => setGuiados((gs) => [...gs, guiadoVazio(metricas[0]?.[0] ?? "")])}
        >
          + pilar
        </Button>

        {metricas.length > 0 && (
          <Glossario termos={metricas.map(([n]) => n)} titulo="O que cada métrica quer dizer" />
        )}
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

      {/* Preço-alvo desta tese: a meta de yield que gera o teto SÓ aqui. É o que separa a tese
          ("dy>6%", um pilar) do critério de entrada ("mira em 8%"), sem que um vire o outro —
          por isso não passa pela guarda "nasce quebrada". */}
      <div className="space-y-2 rounded-lg border p-3">
        <Label htmlFor="meta-yield">Preço-alvo desta tese (opcional)</Label>
        <p className="text-xs text-muted-foreground">
          O yield que gera o preço-alvo só desta tese —{" "}
          <code className="font-mono">teto = provento ÷ meta</code>. Meta mais alta = alvo mais
          baixo, mais exigente.{" "}
          <strong className="text-foreground">Não é um pilar: não quebra a tese.</strong> Vazio usa
          a sua meta padrão.
        </p>
        <div className="relative max-w-40">
          <Input
            id="meta-yield"
            type="number"
            step="0.1"
            min="0"
            inputMode="decimal"
            value={metaPct}
            onChange={(e) => setMetaPct(e.target.value)}
            placeholder="ex.: 8"
            className="font-mono pr-10"
          />
          <span className="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-muted-foreground pointer-events-none">
            %
          </span>
        </div>
      </div>

      {/* Modo avançado: texto cru, para quem já domina a sintaxe. */}
      <div className="space-y-2">
        <button
          type="button"
          onClick={() => setAvancado((v) => !v)}
          className="text-xs text-muted-foreground hover:text-foreground"
        >
          {avancado ? "▾" : "▸"} modo avançado (texto cru)
        </button>
        {avancado && (
          <div className="space-y-2 rounded-lg border border-dashed p-3">
            <p className="text-xs text-muted-foreground">
              Uma linha por pilar. Ex.: <code>payout&lt;80%</code>,{" "}
              <code>divida_ebit&lt;5@2028-06</code>. Em métrica de %, número pelado já é %:{" "}
              <code>dy&gt;6</code> = 6% (ou <code>dy&gt;6%</code> / <code>dy&gt;0.06</code>).
              Múltiplo fica literal: <code>pl&lt;12</code>. Disponíveis:{" "}
              <span className="font-mono">{metricas.map(([n]) => n).join(", ") || "—"}</span>.
            </p>
            {crus.map((c, i) => (
              <div key={i} className="flex gap-2">
                <Input
                  value={c}
                  onChange={(e) =>
                    setCrus((cs) => cs.map((x, idx) => (idx === i ? e.target.value : x)))
                  }
                  placeholder="divida_ebit<5@2028-06"
                  className="font-mono"
                />
                {i === crus.length - 1 && (
                  <Button type="button" variant="outline" onClick={() => setCrus([...crus, ""])}>
                    +
                  </Button>
                )}
              </div>
            ))}
          </div>
        )}
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
        {enviando ? "…" : editando ? "Atualizar tese" : "Registrar tese"}
      </Button>
    </form>
  );
}
