"use client";

import { useEffect, useState } from "react";
import { useRouter, usePathname } from "next/navigation";
import Link from "next/link";

import { getToken, limparToken } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";

const NAV = [
  { href: "/", rotulo: "Teses" },
  { href: "/carteira", rotulo: "Carteira" },
];

/** Casca das telas autenticadas: guarda de acesso + navegação. */
export function Shell({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [ok, setOk] = useState(false);

  useEffect(() => {
    // Sem token → login. A guarda real é a API (todo endpoint exige o Bearer);
    // isto é só a experiência, para não piscar tela protegida.
    if (!getToken()) router.replace("/login");
    else setOk(true);
  }, [router]);

  if (!ok) return null;

  return (
    <div className="flex-1 flex flex-col">
      <header className="border-b">
        <div className="mx-auto max-w-5xl px-4 h-14 flex items-center gap-6">
          <span className="font-semibold">Copiloto</span>
          <nav className="flex gap-1">
            {NAV.map((n) => (
              <Link
                key={n.href}
                href={n.href}
                className={cn(
                  "px-3 py-1.5 rounded-md text-sm",
                  pathname === n.href
                    ? "bg-secondary text-secondary-foreground"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                {n.rotulo}
              </Link>
            ))}
          </nav>
          <Button
            variant="ghost"
            size="sm"
            className="ml-auto text-muted-foreground"
            onClick={() => {
              limparToken();
              router.replace("/login");
            }}
          >
            Sair
          </Button>
        </div>
      </header>
      <main className="mx-auto w-full max-w-5xl px-4 py-8 flex-1">{children}</main>
    </div>
  );
}
