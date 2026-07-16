# API do Copiloto. Build a partir da RAIZ do repo (context: ./repo), porque o app usa caminhos
# relativos à árvore (BACKEND_DIR, data/, leitura do .env). Editable install (-e) mantém o código
# em /app/backend, então __file__ resolve certo — instalar no site-packages quebraria isso.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app/backend

# Editable install (-e) a partir de /app/backend: o código FICA aqui, então __file__ resolve
# certo (BACKEND_DIR, data/, .env). Um install normal copiaria para site-packages e quebraria
# esses caminhos. Deploys são raros, então reinstalar as deps a cada mudança de código é aceitável.
COPY backend/ /app/backend/
RUN pip install -e ".[api]"

# Os dados da CVM (~147 MB) vivem num VOLUME em /app/data — baixados uma vez, persistem entre
# deploys. Não vão para a imagem (bloat + ficam velhos). DATA_DIR = PROJECT_DIR/data = /app/data.
VOLUME ["/app/data"]

EXPOSE 8000

# 1 worker: o avaliador tem cache em memória (a CVM é lida 1x por processo). Mais workers =
# mais cópias do painel na RAM. Para uso próprio, 1 basta.
CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
