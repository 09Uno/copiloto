"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { toast } from "sonner";

import { api, type Veredito, type Posicao, ApiError } from "@/lib/api";
import { brl } from "@/lib/formato";
import { Shell } from "@/components/shell";
import { VeredictoCard } from "@/components/veredito-card";
import { StatTile } from "@/components/visuais";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";

const temProblema = (v: Veredito) =>
  v.resultados.some((r) => r.estado === "CAIU" || r.estado === "PERDEU");
const temAposta = (v: Veredito) => v.resultados.some((r) => r.estado === "APOSTANDO");

/**
 * A tela "Hoje": não uma lista de tudo, mas *o que precisa de você agora*.
 *
 * A ordem é a da urgência: um motivo que caiu num ativo que você TEM pede decisão hoje; uma
 * empresa que você vigia entrando na sua zona é uma janela; um ativo sem tese é uma pergunta
 * em aberto ("por que eu tenho isso?"). O que está de pé recolhe para o fim — silêncio é bom
 * sinal, e o sistema só fala quando algo muda.
 */
export default function HojePage() {
  const router = useRouter();
  const [teses, setTeses] = useState<Veredito[] | null>(null);
  const [posicoes, setPosicoes] = useState<Posicao[]>([]);
  const [alvo, setAlvo] = useState("");

  useEffect(() => {
    Promise.all([
      api.get<Veredito[]>("/api/teses").catch((e) => {
        if (e instanceof ApiError && e.status !== 401) toast.error(e.message);
        return [] as Veredito[];
      }),
      api.get<Posicao[]>("/api/carteira").catch(() => [] as Posicao[]),
    ]).then(([t, p]) => {
      setTeses(t);
      setPosicoes(p);
    });
  }, []);

  function acompanhar(e: React.FormEvent) {
    e.preventDefault();
    const tk = alvo.trim().toUpperCase();
    if (tk) router.push(`/ativo/${tk}`);
  }

  async function encerrar(v: Veredito) {
    const motivo = prompt(
      `Encerrar a tese de ${v.ticker}. Por quê? (vendi / tese morreu / troquei de ideia)`,
    );
    if (!motivo?.trim()) return;
    try {
      await api.del(`/api/teses/${v.tese_id}?motivo=${encodeURIComponent(motivo.trim())}`);
      toast.success(`tese de ${v.ticker} encerrada`);
      setTeses((ts) => ts?.filter((t) => t.tese_id !== v.tese_id) ?? null);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "erro");
    }
  }

  if (teses === null) {
    return (
      <Shell>
        <p className="text-muted-foreground text-sm">carregando…</p>
      </Shell>
    );
  }

  // --- os baldes de atenção
  const comTese = new Set(teses.map((t) => t.ticker));
  const precisa = teses.filter((v) => v.tenho && temProblema(v)); // motivo caiu no que você TEM
  const oportunidades = teses.filter(
    (v) => !v.tenho && !temProblema(v) && v.compra?.estado === "COMPRA",
  );
  const semTese = posicoes.filter((p) => !comTese.has(p.ticker)); // você tem, mas nunca disse por quê
  const apostas = teses.filter((v) => temAposta(v) && !temProblema(v));

  // o resto: de pé, fora de zona — o silêncio saudável, mostrado por último e discreto
  const idsDestaque = new Set([...precisa, ...oportunidades, ...apostas].map((v) => v.tese_id));
  const tranquilo = teses.filter((v) => !idsDestaque.has(v.tese_id));

  const vazio = teses.length === 0 && posicoes.length === 0;

  return (
    <Shell>
      <div className="space-y-8">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="text-2xl font-semibold">Hoje</h1>
            <p className="text-muted-foreground text-sm">
              O que mudou e o que espera uma decisão sua. O sistema só fala quando algo muda.
            </p>
          </div>
          <form onSubmit={acompanhar} className="flex gap-2">
            <Input
              value={alvo}
              onChange={(e) => setAlvo(e.target.value)}
              placeholder="acompanhar empresa (ex.: SAPR11)"
              className="font-mono w-56"
            />
            <Button type="submit" variant="outline" disabled={!alvo.trim()}>
              Acompanhar
            </Button>
          </form>
        </div>

        {vazio ? (
          <div className="rounded-lg border border-dashed p-10 text-center text-muted-foreground">
            <p className="text-foreground">Comece por um dos dois caminhos.</p>
            <p className="text-sm mt-2">
              Escreva acima uma empresa para <em>ficar de olho</em> — ou vá em{" "}
              <Link href="/carteira" className="underline">
                Carteira
              </Link>{" "}
              e registre o que você já tem, para dizer <em>por que</em> comprou.
            </p>
          </div>
        ) : (
          <>
            {/* manchete: os números que resumem a atenção do dia */}
            <div className="grid gap-3 grid-cols-2 lg:grid-cols-4">
              <StatTile
                rotulo="Pedem revisão"
                valor={precisa.length}
                sub="motivo caiu no que você tem"
                tom={precisa.length ? "caiu" : "neutro"}
              />
              <StatTile
                rotulo="Na sua zona"
                valor={oportunidades.length}
                sub="preço entrou no seu alvo"
                tom={oportunidades.length ? "ok" : "neutro"}
              />
              <StatTile
                rotulo="Sem tese"
                valor={semTese.length}
                sub="você tem, mas não disse por quê"
                tom={semTese.length ? "aposta" : "neutro"}
                href="/carteira"
              />
              <StatTile
                rotulo="Apostas em curso"
                valor={apostas.length}
                sub="com prazo para se provar"
                tom={apostas.length ? "aposta" : "neutro"}
              />
            </div>

            {precisa.length > 0 && (
              <Secao
                titulo="Precisa de você"
                dica="Um motivo pelo qual você comprou deixou de valer. A pergunta é sua: compraria hoje?"
              >
                <Grade>
                  {precisa.map((v) => (
                    <VeredictoCard key={v.tese_id} v={v} onEncerrar={encerrar} />
                  ))}
                </Grade>
              </Secao>
            )}

            {oportunidades.length > 0 && (
              <Secao
                titulo="Na sua zona de compra"
                dica="Empresas que você vigia cujo preço entrou no alvo que você mesmo definiu — com os pilares de pé."
              >
                <Grade>
                  {oportunidades.map((v) => (
                    <VeredictoCard key={v.tese_id} v={v} onEncerrar={encerrar} />
                  ))}
                </Grade>
              </Secao>
            )}

            {semTese.length > 0 && (
              <Secao
                titulo="Sem tese ainda"
                dica="Você tem esses ativos, mas nunca registrou por que comprou — então nada os vigia."
              >
                <div className="rounded-lg border divide-y">
                  {semTese.map((p) => (
                    <div
                      key={p.ticker}
                      className="flex items-center justify-between gap-3 px-4 py-3"
                    >
                      <div className="flex items-center gap-3">
                        <Link href={`/ativo/${p.ticker}`} className="font-mono font-medium hover:underline">
                          {p.ticker}
                        </Link>
                        <span className="text-xs text-muted-foreground">{p.classe}</span>
                        <span className="text-xs text-muted-foreground">· {brl(p.investido)}</span>
                      </div>
                      <Button asChild size="sm" variant="outline">
                        <Link href={`/ativo/${p.ticker}`}>Dizer por que comprei</Link>
                      </Button>
                    </div>
                  ))}
                </div>
              </Secao>
            )}

            {apostas.length > 0 && (
              <Secao
                titulo="Apostas em curso"
                dica="Teses com prazo para se provar. Ainda no relógio — o sistema cobra quando o prazo chega."
              >
                <Grade>
                  {apostas.map((v) => (
                    <VeredictoCard key={v.tese_id} v={v} onEncerrar={encerrar} />
                  ))}
                </Grade>
              </Secao>
            )}

            {tranquilo.length > 0 && (
              <Secao
                titulo={`De pé · ${tranquilo.length}`}
                dica="Nada mudou aqui. É o estado que você quer — mostrado por último, de propósito."
              >
                <Grade>
                  {tranquilo.map((v) => (
                    <VeredictoCard key={v.tese_id} v={v} onEncerrar={encerrar} />
                  ))}
                </Grade>
              </Secao>
            )}
          </>
        )}
      </div>
    </Shell>
  );
}

function Secao({
  titulo,
  dica,
  children,
}: {
  titulo: string;
  dica: string;
  children: React.ReactNode;
}) {
  return (
    <section className="space-y-3">
      <div>
        <h2 className="text-sm font-medium uppercase tracking-wide">{titulo}</h2>
        <p className="text-xs text-muted-foreground">{dica}</p>
      </div>
      {children}
    </section>
  );
}

const Grade = ({ children }: { children: React.ReactNode }) => (
  <div className="grid gap-4 sm:grid-cols-2">{children}</div>
);
