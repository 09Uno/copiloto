import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // O dev server trata `localhost` como host canônico e, por segurança, BLOQUEIA os recursos
  // internos (_next/*, HMR) pedidos de outra origem. Abrir por `127.0.0.1` caía nesse bloqueio:
  // sem os chunks, o React não hidratava e a tela ficava em branco. Liberar os dois faz o app
  // funcionar seja qual for o host que você digitar.
  allowedDevOrigins: ["127.0.0.1", "localhost"],

  // Produção: gera um server.js mínimo (só o runtime necessário) para uma imagem Docker enxuta.
  output: "standalone",

  // Em produção o próprio servidor do painel repassa /api → API interna (copiloto-api:8000).
  // Assim o navegador só fala com UM domínio (o painel), a API não fica exposta e não há CORS.
  // Local (sem API_PROXY_TARGET) não reescreve nada — o dev usa NEXT_PUBLIC_API_URL direto.
  async rewrites() {
    const alvo = process.env.API_PROXY_TARGET;
    return alvo ? [{ source: "/api/:path*", destination: `${alvo}/api/:path*` }] : [];
  },
};

export default nextConfig;
