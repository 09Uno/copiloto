"use client";

import { useEffect, useState } from "react";
import { toast } from "sonner";

import { api, ApiError, type Feed } from "@/lib/api";
import { Shell } from "@/components/shell";
import { Button } from "@/components/ui/button";
import { FeedCard } from "@/components/feed-card";

/**
 * O feed de mercado — "o giro" das notícias, com um resumo do que podem significar.
 *
 * GET é de graça (mostra o último feed montado). "Atualizar" é o clique que CUSTA token: busca
 * as notícias e chama a IA. Manual de propósito, como o "buscar o que mudou" dos pilares.
 */
const GRUPOS = [
  { tipo: "ativo", titulo: "Seus ativos" },
  { tipo: "descoberta", titulo: "Giro do mercado" },
  { tipo: "macro", titulo: "Macro" },
];

function dataHora(iso: string): string {
  const d = new Date(iso);
  return isNaN(d.getTime()) ? iso : d.toLocaleString("pt-BR");
}

export default function MercadoPage() {
  const [feed, setFeed] = useState<Feed | null>(null);
  const [disponivel, setDisponivel] = useState<boolean | null>(null);
  const [atualizando, setAtualizando] = useState(false);

  useEffect(() => {
    api
      .get<{ disponivel: boolean }>("/api/feed/disponivel")
      .then((d) => setDisponivel(d.disponivel))
      .catch(() => setDisponivel(false));
    api
      .get<Feed>("/api/feed")
      .then(setFeed)
      .catch((e) => {
        if (e instanceof ApiError && e.status !== 401) toast.error(e.message);
      });
  }, []);

  async function atualizar() {
    setAtualizando(true);
    try {
      setFeed(await api.post<Feed>("/api/feed/atualizar"));
      toast.success("feed atualizado");
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "não consegui atualizar agora");
    } finally {
      setAtualizando(false);
    }
  }

  const itens = feed?.itens ?? [];

  return (
    <Shell>
      <div className="space-y-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-2xl font-semibold">Mercado</h1>
            <p className="text-sm text-muted-foreground">
              O giro das notícias dos seus ativos, do mercado e da macro — com um resumo do que
              pode significar.
              {feed?.gerado_em && <> · atualizado {dataHora(feed.gerado_em)}</>}
            </p>
          </div>
          {disponivel !== false && (
            <Button onClick={atualizar} disabled={atualizando}>
              {atualizando ? "buscando…" : "Atualizar feed"}
            </Button>
          )}
        </div>

        {disponivel === false && (
          <p className="text-sm text-muted-foreground">
            Busca desligada: defina <code className="font-mono">OPENAI_API_KEY</code> em{" "}
            <code className="font-mono">backend/.env</code> para ligar o feed.
          </p>
        )}

        {disponivel !== false && itens.length === 0 && (
          <p className="text-sm text-muted-foreground">
            {feed?.gerado_em
              ? "Nada relevante na imprensa por enquanto."
              : "Clique em “Atualizar feed” para buscar as notícias."}
          </p>
        )}

        {GRUPOS.map((g) => {
          const doGrupo = itens.filter((i) => i.tipo === g.tipo);
          if (doGrupo.length === 0) return null;
          return (
            <section key={g.tipo} className="space-y-3">
              <h2 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                {g.titulo}
              </h2>
              <div className="grid gap-3">
                {doGrupo.map((it, i) => (
                  <FeedCard key={`${it.tipo}-${it.assunto}-${i}`} item={it} />
                ))}
              </div>
            </section>
          );
        })}

        {itens.length > 0 && (
          <p className="text-[11px] italic text-muted-foreground/60">
            a IA resumiu notícias reais e citou as fontes — o “o que pode significar” é contexto de
            mercado, não recomendação de compra ou venda. quem decide é você.
          </p>
        )}
      </div>
    </Shell>
  );
}
