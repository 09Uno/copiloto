// Cliente da API FastAPI. O token JWT vai no header Authorization.
//
// MVP: token em localStorage. É simples e suficiente para uso próprio. Quando houver usuário
// pago, o certo é cookie httpOnly (protege contra XSS) — anotado como hardening.

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";
const CHAVE_TOKEN = "copiloto_token";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(CHAVE_TOKEN);
}

export function setToken(token: string) {
  localStorage.setItem(CHAVE_TOKEN, token);
}

export function limparToken() {
  localStorage.removeItem(CHAVE_TOKEN);
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function req<T>(metodo: string, caminho: string, corpo?: unknown): Promise<T> {
  const token = getToken();
  const r = await fetch(`${BASE}${caminho}`, {
    method: metodo,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: corpo ? JSON.stringify(corpo) : undefined,
  });

  if (r.status === 204) return undefined as T;

  const dados = await r.json().catch(() => ({}));
  if (!r.ok) {
    // A API devolve a mensagem em `detail` — é ela que ensina o usuário
    // ("vai subir não é um pilar verificável…"). Preservar isso é o produto.
    throw new ApiError(r.status, dados?.detail ?? `erro ${r.status}`);
  }
  return dados as T;
}

export const api = {
  get: <T>(c: string) => req<T>("GET", c),
  post: <T>(c: string, corpo?: unknown) => req<T>("POST", c, corpo),
  put: <T>(c: string, corpo?: unknown) => req<T>("PUT", c, corpo),
  del: <T>(c: string) => req<T>("DELETE", c),
};

// ---- tipos que espelham os schemas da API ----

export type Metrica = { nome: string; rotulo: string; valor: number | null; texto: string };
export type Teto = {
  valor: number;
  criterio: string;
  abaixo: boolean;
  margem_pct: number | null;
};
export type Avaliacao = {
  ticker: string;
  classe: string;
  preco: number | null;
  metricas: Metrica[];
  teto: Teto | null;
  alertas: string[];
  sem_criterio: string | null;
  metricas_verificaveis: Record<string, string>;
};
export type Posicao = {
  ticker: string;
  classe: string;
  quantidade: number;
  custo_medio: number;
  investido: number;
  fonte: string;
};
export type Resultado = {
  pilar: string;
  estado: "OK" | "CAIU" | "APOSTANDO" | "PERDEU" | "?" | "PERGUNTAR";
  valor: number | null;
  motivo: string | null;
};
export type Veredito = {
  tese_id: number;
  ticker: string;
  resumo: string;
  resultados: Resultado[];
  de_pe: number;
  total_verificaveis: number;
  pergunta: string;
};
export type Aporte = {
  veredito: string;
  custo_medio_antes: number;
  custo_medio_depois: number;
  yoc_antes: number | null;
  yoc_depois: number | null;
  yield_atual: number | null;
  motivos: string[];
};
