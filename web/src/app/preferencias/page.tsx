"use client";

import { useEffect, useState } from "react";
import { toast } from "sonner";

import { api, type Preferencias, ApiError } from "@/lib/api";
import { brl, pct } from "@/lib/formato";
import { Shell } from "@/components/shell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

/**
 * As alavancas do produto. Sua meta de yield gera o teto ("acima daqui não serve à minha
 * meta"); a margem gera a folga abaixo dele. Todo "preço de compra" que o sistema mostra sai
 * daqui — por isso esta tela existe: o critério é seu, e agora você o move.
 */
export default function PreferenciasPage() {
  const [p, setP] = useState<Preferencias | null>(null);
  const [salvando, setSalvando] = useState(false);

  // Guardamos em % (o que o usuário digita); convertemos para fração ao salvar.
  const [acao, setAcao] = useState("");
  const [fii, setFii] = useState("");
  const [margem, setMargem] = useState("");
  const [alertas, setAlertas] = useState(true);

  useEffect(() => {
    api
      .get<Preferencias>("/api/preferencias")
      .then((pref) => {
        setP(pref);
        setAcao((pref.meta_yield_acao * 100).toString());
        setFii((pref.meta_yield_fii * 100).toString());
        setMargem((pref.margem_seguranca * 100).toString());
        setAlertas(pref.email_alertas);
      })
      .catch((e) => {
        if (e instanceof ApiError && e.status !== 401) toast.error(e.message);
      });
  }, []);

  async function salvar(e: React.FormEvent) {
    e.preventDefault();
    setSalvando(true);
    try {
      const atualizado = await api.put<Preferencias>("/api/preferencias", {
        meta_yield_acao: Number(acao) / 100,
        meta_yield_fii: Number(fii) / 100,
        margem_seguranca: Number(margem) / 100,
        email_alertas: alertas,
      });
      setP(atualizado);
      toast.success("preferências salvas — o teto de todo ativo já reflete elas");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "erro");
    } finally {
      setSalvando(false);
    }
  }

  if (p === null) {
    return (
      <Shell>
        <p className="text-muted-foreground text-sm">carregando…</p>
      </Shell>
    );
  }

  // Ilustração ao vivo: cada R$ 1,00 de provento anual, com a meta e a margem de agora.
  const metaAcao = Number(acao) / 100;
  const margemFrac = Number(margem) / 100;
  const tetoEx = metaAcao > 0 ? 1 / metaAcao : 0;
  const compraEx = tetoEx * (1 - margemFrac);

  return (
    <Shell>
      <form onSubmit={salvar} className="space-y-6 max-w-2xl">
        <div>
          <h1 className="text-2xl font-semibold">Preferências</h1>
          <p className="text-muted-foreground text-sm">
            O critério é seu. Estes números definem o teto e o preço de compra de{" "}
            <em>todo</em> ativo — mude aqui e o sistema recalcula.
          </p>
        </div>

        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Meta de yield</CardTitle>
            <p className="text-sm text-muted-foreground">
              O retorno em provento que você exige. É dela que sai o teto:{" "}
              <span className="font-mono">teto = provento ÷ meta</span>. Meta mais alta = teto
              mais baixo = mais exigente.
            </p>
          </CardHeader>
          <CardContent className="grid gap-4 sm:grid-cols-2">
            <Campo
              id="acao"
              rotulo="Ações"
              sufixo="% a.a."
              valor={acao}
              onChange={setAcao}
              dica="dividend yield mínimo"
            />
            <Campo
              id="fii"
              rotulo="FIIs"
              sufixo="% a.a."
              valor={fii}
              onChange={setFii}
              dica="yield de distribuição mínimo"
            />
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Margem de segurança</CardTitle>
            <p className="text-sm text-muted-foreground">
              A folga que você exige <em>abaixo</em> do teto para chamar de zona de compra.
              Comprar no teto é comprar sem colchão para o erro.
            </p>
          </CardHeader>
          <CardContent>
            <div className="max-w-40">
              <Campo
                id="margem"
                rotulo="Desconto abaixo do teto"
                sufixo="%"
                valor={margem}
                onChange={setMargem}
              />
            </div>
          </CardContent>
        </Card>

        {/* Ilustração: torna concreto o efeito das duas alavancas juntas. */}
        <Card className="border-[var(--dado)]/30">
          <CardHeader className="pb-2">
            <CardTitle className="text-base">O que isso faz, na prática</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-muted-foreground mb-3">
              Uma ação que paga <span className="font-mono">R$ 1,00</span> de provento por ano,
              com a sua meta de <span className="font-mono">{pct(metaAcao, 1)}</span> e margem de{" "}
              <span className="font-mono">{pct(margemFrac, 0)}</span>:
            </p>
            <div className="grid grid-cols-2 gap-3">
              <div className="rounded-lg border p-3">
                <div className="text-xs text-muted-foreground">teto</div>
                <div className="text-2xl font-semibold font-mono tabular-nums">
                  {tetoEx > 0 ? brl(tetoEx) : "—"}
                </div>
                <div className="text-xs text-muted-foreground">acima daqui não serve à meta</div>
              </div>
              <div className="rounded-lg border p-3 border-[var(--ok)]/30">
                <div className="text-xs text-muted-foreground">preço de compra</div>
                <div className="text-2xl font-semibold font-mono tabular-nums text-[var(--ok)]">
                  {compraEx > 0 ? brl(compraEx) : "—"}
                </div>
                <div className="text-xs text-muted-foreground">teto com a sua margem</div>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="pt-6">
            <label className="flex items-start gap-3 cursor-pointer">
              <input
                type="checkbox"
                checked={alertas}
                onChange={(e) => setAlertas(e.target.checked)}
                className="mt-1 size-4 accent-[var(--ok)]"
              />
              <span>
                <span className="text-sm font-medium">Alertas por e-mail</span>
                <span className="block text-xs text-muted-foreground">
                  Receber aviso quando um pilar de uma tese sua deixar de valer.
                </span>
              </span>
            </label>
          </CardContent>
        </Card>

        <div className="flex items-center gap-3">
          <Button type="submit" disabled={salvando}>
            {salvando ? "salvando…" : "Salvar preferências"}
          </Button>
          <span className="text-xs text-muted-foreground">
            afeta o teto e a zona de compra de todos os ativos
          </span>
        </div>
      </form>
    </Shell>
  );
}

function Campo({
  id,
  rotulo,
  sufixo,
  valor,
  onChange,
  dica,
}: {
  id: string;
  rotulo: string;
  sufixo: string;
  valor: string;
  onChange: (v: string) => void;
  dica?: string;
}) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{rotulo}</Label>
      <div className="relative">
        <Input
          id={id}
          type="number"
          step="0.1"
          min="0"
          value={valor}
          onChange={(e) => onChange(e.target.value)}
          className="font-mono pr-16"
          required
        />
        <span className="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-muted-foreground pointer-events-none">
          {sufixo}
        </span>
      </div>
      {dica && <p className="text-xs text-muted-foreground">{dica}</p>}
    </div>
  );
}
