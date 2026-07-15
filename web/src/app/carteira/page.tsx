"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { toast } from "sonner";

import { api, type Posicao, ApiError } from "@/lib/api";
import { brl, pct } from "@/lib/formato";
import { Shell } from "@/components/shell";
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

export default function CarteiraPage() {
  const [pos, setPos] = useState<Posicao[]>([]);
  const [carregando, setCarregando] = useState(true);

  const [ticker, setTicker] = useState("");
  const [qtd, setQtd] = useState("");
  const [custo, setCusto] = useState("");
  const [importando, setImportando] = useState(false);

  async function carregar() {
    try {
      setPos(await api.get<Posicao[]>("/api/carteira"));
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

  return (
    <Shell>
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-semibold">Carteira</h1>
            <p className="text-muted-foreground text-sm">
              {pos.length} ativos · {brl(total)} investido
            </p>
          </div>
          <Button variant="outline" onClick={importarFinControl} disabled={importando}>
            {importando ? "importando…" : "Importar do FinControl"}
          </Button>
        </div>

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
                  className="w-28"
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
                <TableHead>Classe</TableHead>
                <TableHead className="text-right">Qtd</TableHead>
                <TableHead className="text-right">Custo médio</TableHead>
                <TableHead className="text-right">Investido</TableHead>
                <TableHead className="text-right">% carteira</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {pos.map((p) => (
                <TableRow key={p.ticker}>
                  <TableCell className="font-medium">
                    <Link href={`/ativo/${p.ticker}`} className="hover:underline">
                      {p.ticker}
                    </Link>
                  </TableCell>
                  <TableCell className="text-muted-foreground">{p.classe}</TableCell>
                  <TableCell className="text-right">{p.quantidade}</TableCell>
                  <TableCell className="text-right">{brl(p.custo_medio)}</TableCell>
                  <TableCell className="text-right">{brl(p.investido)}</TableCell>
                  <TableCell className="text-right text-muted-foreground">
                    {pct(p.investido / total)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </div>
    </Shell>
  );
}
