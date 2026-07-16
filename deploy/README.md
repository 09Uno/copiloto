# Deploy do Copiloto na VPS

Espelha o padrão dos seus outros sistemas (pasta por app, `proxy-net`, Postgres compartilhado,
Nginx Proxy Manager na frente). **A API sobe primeiro e já destrava o resumo no WhatsApp** — o
n8n a alcança pelo nome interno, sem domínio público. O painel web é o Passo 8.

Nomes usados: banco `copiloto`, usuário `copiloto`, container `copiloto-api`.

---

## 1. Criar o banco no Postgres compartilhado

O n8n mostra que o Postgres é o container `postgres`. Crie ali o banco e o usuário do copiloto
(troque a senha):

```bash
docker exec -i postgres psql -U postgres <<'SQL'
CREATE USER copiloto WITH PASSWORD 'PONHA_UMA_SENHA_FORTE';
CREATE DATABASE copiloto OWNER copiloto;
SQL
```
> Se o superusuário não for `postgres`, use o que existir. `docker exec -it postgres psql -U postgres -c '\du'` lista os usuários.

## 2. Clonar o repo e preparar a pasta

```bash
mkdir -p ~/docker/sistemas/copiloto && cd ~/docker/sistemas/copiloto
git clone <URL_DO_SEU_REPO> repo
cp repo/deploy/docker-compose.yml ./docker-compose.yml
cp repo/deploy/.env.example ./.env
nano .env      # preencha tudo (DATABASE_URL com a senha do passo 1, JWT_SECRET novo, etc.)
```

## 3. Aplicar o schema (portável, idempotente)

```bash
docker exec -i postgres psql -U copiloto -d copiloto -c "CREATE EXTENSION IF NOT EXISTS pgcrypto;"
docker exec -i postgres psql -U copiloto -d copiloto < repo/infra/schema.sql
docker exec -i postgres psql -U copiloto -d copiloto < repo/infra/schema_saas.sql
```

## 4. Migrar seus dados do Supabase (preserva conta, carteira e as 11 teses)

Com o schema já criado, traga só os DADOS. Use a `DATABASE_URL` do Supabase (a que está no seu
`.env` de dev):

```bash
pg_dump --data-only --no-owner --schema=public "SUA_DATABASE_URL_DO_SUPABASE" \
  | docker exec -i postgres psql -U copiloto -d copiloto
```
> Não tem `pg_dump` na VPS? Rode dentro do próprio container: `docker exec postgres pg_dump ...`.
> **Alternativa sem migração:** suba limpo, crie a conta, clique em *Importar do FinControl* e
> registre as teses de novo. Migrar é só pra não reescrever as teses.

## 5. Subir a API

```bash
cd ~/docker/sistemas/copiloto
docker compose up -d --build
docker logs -f copiloto-api      # "Application startup complete."
```

Teste de dentro da rede (o mesmo caminho que o n8n usa):
```bash
docker exec copiloto-api curl -s localhost:8000/api/saude          # {"ok":true}
docker exec copiloto-api curl -s localhost:8000/api/resumo -H "X-Resumo-Token: SEU_RESUMO_TOKEN"
```

## 6. (Opcional) Semear os dados da CVM

Na primeira chamada que precisa de fundamentos, a API baixa ~147 MB da CVM (uns minutos, uma vez
só — depois fica no volume `./cvm_data`). Para pular a espera, copie o cache local pra VPS:
```bash
# na sua máquina:
rsync -av data/ root@srv1649283:~/docker/sistemas/copiloto/cvm_data/
```

## 7. Ligar o resumo diário no n8n

No workflow que eu te passei, troque a URL do nó **"Busca o resumo"** para o **endereço interno**
(n8n e copiloto estão no mesmo `proxy-net`):

```
GET  http://copiloto-api:8000/api/resumo
header  X-Resumo-Token: <RESUMO_TOKEN do .env>
```
Ative o workflow. Todo dia às 08:00 o grupo recebe o resumo. Nenhum domínio público envolvido.

---

## 8. (Depois) Painel web público

Quando quiser abrir a UI no navegador:
1. Descomente o serviço `copiloto-web` no `docker-compose.yml`.
2. No **Nginx Proxy Manager**, crie dois Proxy Hosts (com SSL Let's Encrypt):
   - `copiloto.codetoyou.tech` → `copiloto-web` porta `3000`
   - `copiloto-api.codetoyou.tech` → `copiloto-api` porta `8000`
3. No `.env`, confirme `CORS_ORIGENS=https://copiloto.codetoyou.tech`.
4. `docker compose up -d --build`.
