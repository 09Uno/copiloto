"use client";

import { useState } from "react";
import { GLOSSARIO, verbetes, type Termo } from "@/lib/glossario";

function ChipDirecao({ direcao }: { direcao?: Termo["direcao"] }) {
  if (!direcao) return null;
  return (
    <span
      className={`ml-2 rounded-full px-1.5 py-0.5 text-[10px] font-medium ${
        direcao === "alto"
          ? "bg-[var(--ok)]/15 text-[var(--ok)]"
          : "bg-[var(--dado)]/15 text-[var(--dado)]"
      }`}
    >
      {direcao === "alto" ? "↑ quanto maior, melhor" : "↓ quanto menor, melhor"}
    </span>
  );
}

/**
 * A legenda. Um verbete por termo: o que é e — o que mais importa — POR QUE importa. Recolhida
 * por padrão (não rouba a cena de quem já sabe), mas a um clique de quem está aprendendo.
 * `termos` filtra para os que aparecem na tela; sem ele, mostra todos.
 */
export function Glossario({
  termos,
  titulo = "Entenda os termos",
}: {
  termos?: string[];
  titulo?: string;
}) {
  const [aberto, setAberto] = useState(false);
  const lista = verbetes(termos ?? Object.keys(GLOSSARIO));
  if (lista.length === 0) return null;

  return (
    <div className="rounded-lg border">
      <button
        type="button"
        onClick={() => setAberto((v) => !v)}
        className="flex w-full items-center gap-2 px-4 py-3 text-sm text-muted-foreground hover:text-foreground"
      >
        <span aria-hidden>ⓘ</span>
        <span className="font-medium">{titulo}</span>
        <span className="ml-auto text-xs">{aberto ? "▾" : "▸"}</span>
      </button>
      {aberto && (
        <dl className="divide-y border-t">
          {lista.map(([chave, t]) => (
            <div key={chave} className="px-4 py-3">
              <dt className="text-sm font-medium flex flex-wrap items-center">
                {t.rotulo}
                <ChipDirecao direcao={t.direcao} />
              </dt>
              <dd className="mt-1 text-sm text-muted-foreground">
                {t.oquee}{" "}
                <span className="text-foreground/80">
                  <span className="font-medium">Por que importa:</span> {t.porque}
                </span>
              </dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  );
}

/** Explicação compacta de UM termo — para mostrar ao lado da métrica que o usuário acabou de
 *  escolher no construtor de tese. Silencioso se a chave não tem verbete. */
export function ExplicaTermo({ chave }: { chave: string }) {
  const t = GLOSSARIO[chave];
  if (!t) return null;
  return (
    <p className="text-xs text-muted-foreground">
      <span className="font-medium text-foreground/80">{t.rotulo}:</span> {t.oquee}{" "}
      <span className="font-medium">Por quê:</span> {t.porque}
    </p>
  );
}
