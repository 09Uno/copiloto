"""Auth próprio (bcrypt + JWT) — portável, sem Supabase.

O que estes testes protegem: a senha nunca vira texto no banco, um token forjado é recusado, e
o limite de 72 bytes do bcrypt não deixa passar senha truncada em silêncio.
"""

from __future__ import annotations

import time
import uuid

import jwt
import pytest

from app.api import auth


@pytest.fixture(autouse=True)
def _segredo(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "segredo-de-teste-nao-use-em-producao")


def test_a_senha_nunca_vira_texto_no_banco():
    h = auth.hash_senha("minha-senha-secreta")

    assert "minha-senha-secreta" not in h
    assert h.startswith("$2")  # prefixo bcrypt
    assert auth.conferir_senha("minha-senha-secreta", h)
    assert not auth.conferir_senha("senha-errada", h)


def test_hashes_do_mesmo_texto_sao_diferentes():
    """Salt: dois hashes da mesma senha não podem ser iguais, senão dá para tabelar."""
    assert auth.hash_senha("igual") != auth.hash_senha("igual")


def test_senha_longa_demais_e_RECUSADA_nao_truncada():
    """bcrypt ignora bytes além de 72 — aceitar seria validar uma senha que o usuário não
    escolheu (os primeiros 72 bytes). Melhor recusar no cadastro."""
    with pytest.raises(ValueError, match="longa demais"):
        auth.hash_senha("x" * 100)


def test_token_ida_e_volta():
    uid = uuid.uuid4()
    token = auth.emitir_token(uid, "bruno@exemplo.com")
    payload = auth.validar_token(token)

    assert payload["sub"] == str(uid)
    assert payload["email"] == "bruno@exemplo.com"


def test_token_forjado_com_outro_segredo_e_recusado():
    """A defesa central: um token assinado com outra chave NÃO pode ser aceito."""
    falso = jwt.encode({"sub": "invasor", "exp": time.time() + 3600},
                       "outro-segredo", algorithm="HS256")

    with pytest.raises(jwt.InvalidTokenError):
        auth.validar_token(falso)


def test_token_expirado_e_recusado():
    # Token com exp no passado, assinado com o MESMO segredo — só a expiração deve barrá-lo.
    vencido = jwt.encode(
        {"sub": str(uuid.uuid4()), "exp": int(time.time()) - 10},
        auth._segredo(), algorithm=auth.ALG,
    )
    with pytest.raises(jwt.ExpiredSignatureError):
        auth.validar_token(vencido)


def test_sem_JWT_SECRET_a_api_nao_finge_que_esta_segura(monkeypatch):
    """Sem segredo, qualquer token seria aceito. Falhar é mais seguro que rodar inseguro."""
    monkeypatch.delenv("JWT_SECRET", raising=False)
    monkeypatch.setattr(auth, "BACKEND_DIR", type(auth.BACKEND_DIR)("/caminho/inexistente"))

    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        auth.emitir_token(uuid.uuid4(), "x@y.com")
