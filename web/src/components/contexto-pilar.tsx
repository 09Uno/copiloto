"use client";

import { useState } from "react";
import { api, ApiError, type Contexto } from "@/lib/api";

/**
 * O "buscar o que mudou" de um pilar que só você julga.
 *
 * A IA NÃO dá veredito — ela traz as notícias que tocam a afirmação, citadas, e VOCÊ decide.
 * Por isso o rodapé sempre lembra: "quem julga é você". A cor marca só se a matéria parece
 * a favor ou contra a tese — não é recomendação, é a direção da evidência.
 */
function corRelevancia(r: string): string {
  if (r === "a favor") return "text-[var(--ok)]";
  if (r === "contra") return "text-[var(--caiu)]";
  return "text-muted-foreground";
}

function dataCurta(iso: string): string {
  const d = new Date(iso);
  return isNaN(d.getTime()) ? iso : d.toLocaleDateString("pt-BR");
}

export function ContextoPilar({
  pilarId,
  inicial,
}: {
  pilarId: number;
  inicial: Contexto | null;
}) {
  const [ctx, setCtx] = useState<Contexto | null>(inicial);
  const [carregando, setCarregando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  async function buscar() {
    setCarregando(true);
    setErro(null);
    try {
      setCtx(await api.post<Contexto>(`/api/contexto/pilar/${pilarId}`));
    } catch (e) {
      setErro(e instanceof ApiError ? e.message : "não consegui buscar agora");
    } finally {
      setCarregando(false);
    }
  }

  return (
    <div className="mt-1.5 space-y-1">
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={buscar}
          disabled={carregando}
          className="text-xs text-muted-foreground hover:text-foreground underline decoration-dotted underline-offset-2 disabled:opacity-50"
        >
          {carregando ? "buscando…" : ctx ? "buscar de novo" : "🔎 buscar o que mudou"}
        </button>
        {ctx && (
          <span className="text-[11px] text-muted-foreground/70">
            última: {dataCurta(ctx.buscado_em)}
          </span>
        )}
      </div>

      {erro && <p className="text-xs text-[var(--caiu)]">{erro}</p>}

      {ctx && ctx.nada_mudou && (
        <p className="text-xs text-muted-foreground">
          nada relevante na imprensa desde a última checagem.
        </p>
      )}

      {ctx && ctx.achados.length > 0 && (
        <>
          <ul className="space-y-1">
            {ctx.achados.map((a, i) => (
              <li key={i} className="text-xs leading-snug">
                <a
                  href={a.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="hover:underline"
                >
                  <span className={`font-medium ${corRelevancia(a.relevancia)}`}>
                    [{a.relevancia}]
                  </span>{" "}
                  <span className="text-foreground/90">{a.resumo}</span>
                  <span className="text-muted-foreground/70">
                    {" — "}
                    {a.fonte}
                    {a.data ? `, ${dataCurta(a.data)}` : ""}
                  </span>
                </a>
              </li>
            ))}
          </ul>
          <p className="text-[10px] italic text-muted-foreground/60">
            a IA só trouxe as notícias — quem julga se o pilar ainda vale é você.
          </p>
        </>
      )}
    </div>
  );
}
