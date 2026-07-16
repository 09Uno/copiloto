"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { toast } from "sonner";

import { api, type Posicao, type Veredito, ApiError } from "@/lib/api";
import { brl, pct } from "@/lib/formato";
import { Shell } from "@/components/shell";
import { Alocacao, SeloTese, type EstadoTese } from "@/components/visuais";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

/** O estado da tese de um ativo — a ponte entre "o que tenho" e "por que tenho". */
function estadoDaTese(v: Veredito | undefined): EstadoTese {
  if (!v) return "sem_tese";
  if (v.resultados.some((r) => r.estado === "CAIU" || r.estado === "PERDEU")) return "caiu";
  if (v.resultados.some((r) => r.estado === "APOSTANDO")) return "aposta";
  return "de_pe";
}

export default function CarteiraPage() {
  const [pos, setPos] = useState<Posicao[]>([]);
  const [teses, setTeses] = useState<Record<string, Veredito>>({});
  const [carregando, setCarregando] = useState(true);

  const [ticker, setTicker] = useState("");
  const [qtd, setQtd] = useState("");
  const [custo, setCusto] = useState("");
  const [importando, setImportando] = useState(false);

  async function carregar() {
    try {
      const [p, t] = await Promise.all([
        api.get<Posicao[]>("/api/carteira"),
        api.get<Veredito[]>("/api/teses").catch(() => [] as Veredito[]),
      ]);
      setPos(p);
      setTeses(Object.fromEntries(t.map((v) => [v.ticker, v])));
    } catch (e) {
      if (e instanceof ApiError && e.status !== 401) toast.error(e.message);
    } finally {
      setCarregando(false);
    }
  }
  useEffect(() => {
    carregar();
  }, []);

  async function adicionar(e: React.FormEvent) {
    e.preventDefault();
    try {
      await api.put("/api/carteira/posicao", {
        ticker,
        quantidade: Number(qtd),
        custo_medio: Number(custo),
      });
      setTicker("");
      setQtd("");
      setCusto("");
      toast.success("posição salva");
      carregar();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "erro");
    }
  }

  async function remover(tk: string) {
    if (!confirm(`Remover ${tk} da carteira? A tese, se houver, continua registrada.`)) return;
    try {
      await api.del(`/api/carteira/posicao/${tk}`);
      toast.success(`${tk} removido`);
      carregar();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "erro");
    }
  }

  async function importarFinControl() {
    // MVP: pede as credenciais na hora. Depois vira uma fonte salva por usuário.
    const url = prompt("URL do FinControl", "https://fincontrol.codetoyou.tech");
    if (!url) return;
    const usuario = prompt("usuário / e-mail");
    if (!usuario) return;
    const senha = prompt("senha");
    if (!senha) return;

    setImportando(true);
    try {
      const r = await api.post<{ importadas: number }>("/api/carteira/sync/fincontrol", {
        url,
        usuario,
        senha,
      });
      toast.success(`${r.importadas} posições importadas`);
      carregar();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "erro");
    } finally {
      setImportando(false);
    }
  }

  const total = pos.reduce((s, p) => s + p.investido, 0);
  const semTese = pos.filter((p) => !teses[p.ticker]).length;

  return (
    <Shell>
      <div className="space-y-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-2xl font-semibold">Carteira</h1>
            <p className="text-muted-foreground text-sm">
              {pos.length} ativos · {brl(total)} investido
              {semTese > 0 && (
                <>
                  {" · "}
                  <span className="text-[var(--aposta)]">{semTese} sem tese</span>
                </>
              )}
            </p>
          </div>
          <Button variant="outline" onClick={importarFinControl} disabled={importando}>
            {importando ? "importando…" : "Importar do FinControl"}
          </Button>
        </div>

        {/* Alocação: quanto cada ativo pesa. Barra de magnitude, não pizza — comparar
            comprimentos é mais preciso que comparar fatias. */}
        {pos.length > 0 && (
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base">Como está distribuída</CardTitle>
            </CardHeader>
            <CardContent>
              <Alocacao
                itens={pos.map((p) => ({
                  rotulo: p.ticker,
                  valor: p.investido,
                  href: `/ativo/${p.ticker}`,
                }))}
              />
            </CardContent>
          </Card>
        )}

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Adicionar posição</CardTitle>
          </CardHeader>
          <CardContent>
            <form onSubmit={adicionar} className="flex flex-wrap items-end gap-3">
              <div className="space-y-1">
                <Label htmlFor="tk">Ativo</Label>
                <Input
                  id="tk"
                  value={ticker}
                  onChange={(e) => setTicker(e.target.value.toUpperCase())}
                  placeholder="TAEE3"
                  className="w-28 font-mono"
                  required
                />
              </div>
              <div className="space-y-1">
                <Label htmlFor="q">Quantidade</Label>
                <Input
                  id="q"
                  type="number"
                  step="any"
                  value={qtd}
                  onChange={(e) => setQtd(e.target.value)}
                  className="w-28"
                  required
                />
              </div>
              <div className="space-y-1">
                <Label htmlFor="c">Custo médio</Label>
                <Input
                  id="c"
                  type="number"
                  step="any"
                  value={custo}
                  onChange={(e) => setCusto(e.target.value)}
                  className="w-32"
                  required
                />
              </div>
              <Button type="submit">Salvar</Button>
            </form>
          </CardContent>
        </Card>

        {carregando ? (
          <p className="text-muted-foreground text-sm">carregando…</p>
        ) : pos.length === 0 ? (
          <p className="text-muted-foreground text-sm">
            Nenhuma posição. Adicione uma acima ou importe do FinControl.
          </p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Ativo</TableHead>
                <TableHead>Tese</TableHead>
                <TableHead className="text-right">Qtd</TableHead>
                <TableHead className="text-right">Custo médio</TableHead>
                <TableHead className="text-right">Investido</TableHead>
                <TableHead className="text-right">% carteira</TableHead>
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {pos.map((p) => {
                const estado = estadoDaTese(teses[p.ticker]);
                return (
                  <TableRow key={p.ticker}>
                    <TableCell className="font-medium">
                      <Link href={`/ativo/${p.ticker}`} className="font-mono hover:underline">
                        {p.ticker}
                      </Link>
                      <span className="ml-2 text-xs text-muted-foreground">{p.classe}</span>
                    </TableCell>
                    <TableCell>
                      {estado === "sem_tese" ? (
                        <Link href={`/ativo/${p.ticker}`}>
                          <SeloTese estado="sem_tese" />
                        </Link>
                      ) : (
                        <SeloTese estado={estado} />
                      )}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">{p.quantidade}</TableCell>
                    <TableCell className="text-right tabular-nums">{brl(p.custo_medio)}</TableCell>
                    <TableCell className="text-right tabular-nums">{brl(p.investido)}</TableCell>
                    <TableCell className="text-right text-muted-foreground tabular-nums">
                      {pct(p.investido / total)}
                    </TableCell>
                    <TableCell className="text-right">
                      <Button
                        variant="ghost"
                        size="icon-xs"
                        className="text-muted-foreground hover:text-[var(--caiu)]"
                        onClick={() => remover(p.ticker)}
                        title="remover da carteira"
                      >
                        ✕
                      </Button>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        )}
      </div>
    </Shell>
  );
}
