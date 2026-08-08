"""Suíte do modo WEB: Postgres, multi-tenant e login por e-mail.

Roda em processo SEPARADO da suíte `tests/` porque `app/config.py` decide o
modo (LOCAL ou WEB) na importação, olhando DATABASE_URL. Definir a variável
aqui, antes de qualquer `import app`, é o que coloca o app em modo WEB.

    pytest tests          # desktop / SQLite
    pytest tests_web      # hospedado / Postgres

Precisa de um Postgres 15+ acessível em DATABASE_URL_TESTE; sem ele a suíte é
pulada em vez de falhar, para não travar quem só mexe no desktop.
"""

import os

_URL = os.environ.get("DATABASE_URL_TESTE", "")
if _URL:
    os.environ["DATABASE_URL"] = _URL
    os.environ.setdefault("SUPER_ADMIN_EMAIL", "chefe@exemplo.com")
    os.environ.setdefault("SECRET_KEY", "segredo-de-teste")
    os.environ.setdefault("COOKIE_SEGURO", "0")

import pytest  # noqa: E402

pytestmark = pytest.mark.skipif(not _URL, reason="DATABASE_URL_TESTE não definida")

if not _URL:  # sem banco não há o que preparar
    collect_ignore_glob = ["*"]


from fastapi.testclient import TestClient  # noqa: E402

from app.auth import email_envio, repo  # noqa: E402
from app.db import postgres  # noqa: E402
from app.db.migrations import preparar_congregacao  # noqa: E402
from app.main_api import create_app  # noqa: E402


@pytest.fixture
def banco_limpo():
    """Schema zerado e recriado a cada teste: isolamento é justamente o que se
    testa aqui, e um resíduo de outro teste tornaria o resultado sem valor."""
    import app.main_api as main_api
    from app.db.migrations import run_migrations

    with postgres.get_connection(super_admin=True) as conn:
        conn.executescript("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")

    run_migrations()
    # `create_app` só migra no primeiro request; como o schema acabou de ser
    # recriado aqui, o app pode considerar a migração feita.
    main_api._migracao_feita = True
    yield


@pytest.fixture
def caixa_de_entrada(monkeypatch):
    """Captura os e-mails em vez de enviá-los, e devolve o código de cada um."""
    enviados: list[dict] = []

    def _falso_enviar(destinatario, assunto, corpo_texto, corpo_html=""):
        enviados.append({"para": destinatario, "assunto": assunto, "texto": corpo_texto})
        return "resend"

    monkeypatch.setattr(email_envio, "enviar", _falso_enviar)
    # `email_configurado` decide se um e-mail comum pode receber código;
    # com a caixa falsa no lugar, o envio "funciona".
    monkeypatch.setattr("app.config.RESEND_API_KEY", "chave-de-teste")
    return enviados


def codigo_de(enviados: list[dict], email: str) -> str:
    import re

    for msg in reversed(enviados):
        if msg["para"] == email:
            achado = re.search(r"\b(\d{6})\b", msg["texto"])
            if achado:
                return achado.group(1)
    raise AssertionError(f"nenhum código enviado para {email}: {enviados}")


@pytest.fixture
def cliente(banco_limpo):
    with TestClient(create_app(), follow_redirects=False) as c:
        yield c


def entrar(cliente: TestClient, enviados: list[dict], email: str) -> None:
    """Faz o login completo (pedir código -> confirmar) e deixa o cookie posto."""
    resposta = cliente.post("/entrar", data={"email": email})
    assert resposta.status_code == 200, resposta.text[:400]
    codigo = codigo_de(enviados, email)
    resposta = cliente.post("/entrar/codigo", data={"email": email, "codigo": codigo})
    assert resposta.status_code == 303, resposta.text[:400]
    assert cliente.cookies.get("escala_sessao")


def criar_congregacao(nome: str) -> int:
    with postgres.get_connection(super_admin=True) as conn:
        congregacao = repo.criar_congregacao(conn, nome)
        preparar_congregacao(conn, congregacao.id)
        return congregacao.id


def dar_acesso(email: str, congregacao_id: int, papel) -> int:
    with postgres.get_connection(super_admin=True) as conn:
        usuario = repo.obter_ou_criar_usuario(conn, email, email.split("@")[0])
        repo.definir_membro(conn, usuario.id, congregacao_id, papel)
        return usuario.id
