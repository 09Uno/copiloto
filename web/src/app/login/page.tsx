"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";

import { api, setToken, ApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

type Resp = { token: string; email: string; nome: string | null };

export default function LoginPage() {
  const router = useRouter();
  const [modo, setModo] = useState<"login" | "cadastro">("login");
  const [email, setEmail] = useState("");
  const [senha, setSenha] = useState("");
  const [carregando, setCarregando] = useState(false);

  async function enviar(e: React.FormEvent) {
    e.preventDefault();
    setCarregando(true);
    try {
      const rota = modo === "login" ? "/api/auth/login" : "/api/auth/cadastro";
      const r = await api.post<Resp>(rota, { email, senha });
      setToken(r.token);
      router.push("/");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "algo deu errado");
    } finally {
      setCarregando(false);
    }
  }

  return (
    <main className="flex-1 grid place-items-center px-4">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle className="text-2xl">Copiloto</CardTitle>
          <CardDescription>
            Guarde por que você comprou. O sistema avisa quando o motivo deixar de valer.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={enviar} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="email">E-mail</Label>
              <Input
                id="email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                autoComplete="email"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="senha">Senha</Label>
              <Input
                id="senha"
                type="password"
                value={senha}
                onChange={(e) => setSenha(e.target.value)}
                required
                minLength={8}
                autoComplete={modo === "login" ? "current-password" : "new-password"}
              />
            </div>
            <Button type="submit" className="w-full" disabled={carregando}>
              {carregando ? "…" : modo === "login" ? "Entrar" : "Criar conta"}
            </Button>
          </form>

          <button
            onClick={() => setModo(modo === "login" ? "cadastro" : "login")}
            className="mt-4 text-sm text-muted-foreground hover:text-foreground w-full text-center"
          >
            {modo === "login"
              ? "Não tem conta? Criar uma"
              : "Já tem conta? Entrar"}
          </button>
        </CardContent>
      </Card>
    </main>
  );
}
