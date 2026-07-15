"use client";

import { useEffect, useState } from "react";
import { toast } from "sonner";

import { api, type Veredito, ApiError } from "@/lib/api";
import { Shell } from "@/components/shell";
import { VeredictoCard } from "@/components/veredito-card";

export default function PainelPage() {
  const [teses, setTeses] = useState<Veredito[] | null>(null);

  useEffect(() => {
    api
      .get<Veredito[]>("/api/teses")
      .then(setTeses)
      .catch((e) => {
        setTeses([]);
        if (e instanceof ApiError && e.status !== 401) toast.error(e.message);
      });
  }, []);

  return (
    <Shell>
      <div className="space-y-6">
        <div>
          <h1 className="text-2xl font-semibold">Suas teses</h1>
          <p className="text-muted-foreground text-sm">
            Por que você comprou — e se ainda vale. O sistema avisa só quando algo muda.
          </p>
        </div>

        {teses === null ? (
          <p className="text-muted-foreground text-sm">carregando…</p>
        ) : teses.length === 0 ? (
          <div className="rounded-lg border border-dashed p-10 text-center text-muted-foreground">
            <p>Nenhuma tese ainda.</p>
            <p className="text-sm mt-1">
              Abra um ativo na sua carteira e escreva <em>por que</em> você comprou.
            </p>
          </div>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2">
            {teses.map((v) => (
              <VeredictoCard key={v.tese_id} v={v} />
            ))}
          </div>
        )}
      </div>
    </Shell>
  );
}
