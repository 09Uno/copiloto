"""Telegram — o canal que te encontra.

Um dashboard aberto não serve: você não vai ficar olhando para uma tela esperando o balanço
do 3º trimestre da Sanepar sair. O alerta tem de ir até você.

Sem token configurado, o módulo **não falha** — ele devolve `False` e o `vigia` imprime na tela.
Melhor uma ferramenta que funciona pela metade do que uma que não roda.
"""

from __future__ import annotations

import os

import httpx

from app.core.config import BACKEND_DIR


def _env(chave: str) -> str | None:
    if v := os.getenv(chave):
        return v
    env = BACKEND_DIR / ".env"
    if env.exists():
        for linha in env.read_text(encoding="utf-8").splitlines():
            linha = linha.strip()
            if linha.startswith(f"{chave}="):
                return linha.split("=", 1)[1].strip()
    return None


def configurado() -> bool:
    return bool(_env("TELEGRAM_TOKEN") and _env("TELEGRAM_CHAT_ID"))


def enviar(texto: str) -> bool:
    token, chat = _env("TELEGRAM_TOKEN"), _env("TELEGRAM_CHAT_ID")
    if not (token and chat):
        return False

    try:
        r = httpx.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": chat,
                "text": texto[:4000],  # o Telegram corta em 4096
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=30.0,
        )
        return r.status_code == 200
    except httpx.RequestError:
        return False


COMO_CONFIGURAR = """
Para receber os alertas no Telegram:

  1. Fale com o @BotFather no Telegram e mande /newbot
  2. Ele devolve um TOKEN
  3. Mande qualquer mensagem para o SEU bot
  4. Abra https://api.telegram.org/bot<TOKEN>/getUpdates e pegue o "chat":{"id": ...}
  5. Ponha no backend/.env:

     TELEGRAM_TOKEN=123456:ABC-DEF...
     TELEGRAM_CHAT_ID=123456789

Sem isso o vigia continua funcionando — só imprime na tela em vez de te avisar.
""".strip()
