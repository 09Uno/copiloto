# Painel do Copiloto (Next.js 16, output: standalone). Build a partir da RAIZ do repo
# (context: ./repo), então os COPY referenciam web/.
#
# NEXT_PUBLIC_API_URL é assado no bundle no BUILD (o navegador chama a API direto). Por isso
# vem como ARG e precisa ser a URL PÚBLICA da API — não o nome interno do container.

# ── deps: cacheia node_modules enquanto o package-lock não muda ──────────────────
FROM node:22-slim AS deps
WORKDIR /app
COPY web/package.json web/package-lock.json ./
RUN npm ci

# ── build: compila o Next em modo standalone ─────────────────────────────────────
FROM node:22-slim AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY web/ ./
ARG NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

# ── runner: só o runtime mínimo ──────────────────────────────────────────────────
FROM node:22-slim AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV PORT=3000
ENV HOSTNAME=0.0.0.0

# O standalone traz um server.js + node_modules podados; static e public entram à parte.
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public

EXPOSE 3000
CMD ["node", "server.js"]
