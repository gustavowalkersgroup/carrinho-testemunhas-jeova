import os
import sys
from pathlib import Path


def _resolve_base_dir() -> Path:
    """Onde os dados do usuário (banco, PDFs gerados) devem morar: sempre ao lado
    do .exe quando congelado, nunca dentro do bundle temporário do PyInstaller."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _resolve_resources_dir() -> Path:
    """Onde os recursos somente-leitura empacotados (templates, seeds, schema.sql)
    ficam: sys._MEIPASS quando congelado (onde o PyInstaller extrai `datas`),
    ou a raiz do repositório em desenvolvimento."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parent.parent


def _env(nome: str, padrao: str = "") -> str:
    return (os.environ.get(nome) or padrao).strip()


def _env_bool(nome: str, padrao: bool = False) -> bool:
    valor = _env(nome).lower()
    if not valor:
        return padrao
    return valor in {"1", "true", "yes", "on", "sim"}


BASE_DIR = _resolve_base_dir()
DATA_DIR = BASE_DIR / "data"
ESCALAS_DIR = DATA_DIR / "escalas"
DB_PATH = DATA_DIR / "carrinho.db"

# Redefinido mais abaixo, quando o modo WEB é detectado: lá o disco é
# somente-leitura fora de /tmp, e escrever ao lado do código falha.

RESOURCES_DIR = _resolve_resources_dir()
APP_DIR = RESOURCES_DIR / "app"
SEEDS_DIR = APP_DIR / "seeds"
TEMPLATES_DIR = APP_DIR / "web" / "templates"
STATIC_DIR = APP_DIR / "web" / "static"
SCHEMA_PATH = APP_DIR / "db" / "schema.sql"
SCHEMA_PG_PATH = APP_DIR / "db" / "schema_pg.sql"

HOST = "127.0.0.1"
PORT = 8756


# === Modo de execução ======================================================
# O mesmo código roda em dois modos:
#
#   LOCAL  — app de desktop (pywebview + SQLite num arquivo ao lado do .exe).
#            Uma congregação só, sem login: quem abriu o programa no próprio
#            computador já é o dono dos dados.
#
#   WEB    — hospedado (Vercel + Postgres). Várias congregações no mesmo banco,
#            login por e-mail obrigatório e isolamento entre congregações
#            garantido por Row Level Security no Postgres.
#
# A chave é DATABASE_URL: existindo, é modo WEB. Assim o desktop continua
# funcionando exatamente como antes, sem nenhuma variável de ambiente.

# A integração Neon da Vercel nem sempre expõe a variável como `DATABASE_URL`:
# dependendo do prefixo escolhido na tela de Storage, o nome vira
# `DATABASE_POSTGRES_URL`, `DATABASE_POSTGRES_PRISMA_URL` etc. Por isso
# procuramos várias variações conhecidas, na ordem de preferência (pooler +
# sslmode primeiro; sem pooler/sem SSL só como último recurso).
_CANDIDATOS_DATABASE_URL = (
    "DATABASE_URL",
    "POSTGRES_URL",
    "DATABASE_POSTGRES_URL",
    "DATABASE_POSTGRES_PRISMA_URL",
    "POSTGRES_PRISMA_URL",
    "DATABASE_POSTGRES_URL_NON_POOLING",
    "POSTGRES_URL_NON_POOLING",
    "DATABASE_POSTGRES_URL_NO_SSL",
    "POSTGRES_URL_NO_SSL",
)


def _resolver_database_url() -> str:
    for nome in _CANDIDATOS_DATABASE_URL:
        valor = _env(nome)
        if valor:
            return valor
    return ""


DATABASE_URL = _resolver_database_url()
MODO_WEB = bool(DATABASE_URL)
MODO_LOCAL = not MODO_WEB

if MODO_WEB:
    # Em serverless, o único lugar gravável é o diretório temporário — e ele
    # some quando a instância é reciclada, o que é exatamente o que se quer
    # para um PDF que já foi baixado. No desktop nada disso muda: o arquivo
    # continua sendo gerado ao lado do executável, onde o usuário o encontra.
    import tempfile

    DATA_DIR = Path(tempfile.gettempdir()) / "escala-carrinho"
    ESCALAS_DIR = DATA_DIR / "escalas"

# congregação usada no modo LOCAL (banco de uma congregação só)
CONGREGACAO_LOCAL_ID = 1


# === Autenticação (só usada no modo WEB) ===================================

# Quem administra a instalação inteira: aprova solicitações de acesso, cria e
# remove congregações, promove outros administradores. Aceita vários e-mails
# separados por vírgula. Sem isso, ninguém consegue aprovar ninguém — é a
# única porta de entrada de uma instalação nova.
SUPER_ADMIN_EMAILS = [
    e.strip().lower() for e in _env("SUPER_ADMIN_EMAIL").split(",") if e.strip()
]

# Assina os cookies de sessão. Em produção precisa ser um valor fixo e secreto:
# se mudar, todas as sessões abertas caem. Sem valor definido usamos um segredo
# efêmero por processo — bom o suficiente para desenvolvimento, inútil em
# produção (cada instância serverless teria um segredo diferente), por isso
# main_api avisa em log quando isso acontece no modo WEB.
SECRET_KEY = _env("SECRET_KEY")

SESSAO_COOKIE = "escala_sessao"
SESSAO_DURACAO_DIAS = 30
# Validade do código de 6 dígitos enviado por e-mail.
CODIGO_LOGIN_VALIDADE_MINUTOS = 15
# Tentativas erradas do mesmo código antes de invalidá-lo (evita força bruta
# num espaço de só 1 milhão de combinações).
CODIGO_LOGIN_MAX_TENTATIVAS = 5
# Códigos pedidos por e-mail dentro da janela, antes de recusar novos pedidos.
CODIGO_LOGIN_MAX_POR_HORA = 8
# Solicitações de acesso (formulário público) por hora, no total, antes de
# suspender os avisos por e-mail aos administradores. Os pedidos continuam
# sendo gravados; só o aviso para, para não entupir caixa nem cota de envio.
SOLICITACOES_AVISO_MAX_POR_HORA = 20


# === Envio de e-mail =======================================================
# Ordem de preferência: Resend (HTTP, funciona em serverless) -> SMTP -> log.
# O modo "log" existe para o primeiro acesso de uma instalação recém-criada:
# sem provedor configurado, só o super-admin consegue entrar e o código sai
# no log da função (visível no painel da Vercel). Para qualquer outro e-mail
# o login é recusado, senão bastaria digitar um e-mail alheio para entrar.
RESEND_API_KEY = _env("RESEND_API_KEY")
EMAIL_REMETENTE = _env("EMAIL_FROM", "Escala do Carrinho <onboarding@resend.dev>")
SMTP_HOST = _env("SMTP_HOST")
SMTP_PORT = int(_env("SMTP_PORT", "587") or "587")
SMTP_USER = _env("SMTP_USER")
SMTP_PASSWORD = _env("SMTP_PASSWORD")

# URL pública da instalação, usada nos links dentro dos e-mails. Na Vercel,
# VERCEL_PROJECT_PRODUCTION_URL vem preenchida automaticamente.
_VERCEL_URL = _env("VERCEL_PROJECT_PRODUCTION_URL") or _env("VERCEL_URL")
APP_BASE_URL = _env("APP_BASE_URL") or (f"https://{_VERCEL_URL}" if _VERCEL_URL else "")

# Cookies só por HTTPS. Desligue apenas para testar o modo WEB em http://localhost.
COOKIE_SEGURO = _env_bool("COOKIE_SEGURO", MODO_WEB)


def email_configurado() -> bool:
    return bool(RESEND_API_KEY or (SMTP_HOST and SMTP_USER))


CONGREGACAO_NOME = "Congr. Parque das Nações"
CONTATO_RESPONSAVEL = "Benedito (19) 99433-2671"

# meses sem designação nova para uma dupla "não repetir" deixar de valer
JANELA_MESES_EVITAR_REPETIR_DUPLA = 6

DIAS_SEMANA_ORDEM = [
    "SEGUNDA",
    "TERCA",
    "QUARTA",
    "QUINTA",
    "SEXTA",
    "SABADO",
    "DOMINGO",
]

DIAS_SEMANA_LABEL = {
    "SEGUNDA": "Segunda",
    "TERCA": "Terça",
    "QUARTA": "Quarta",
    "QUINTA": "Quinta",
    "SEXTA": "Sexta",
    "SABADO": "Sábado",
    "DOMINGO": "Domingo",
}

# datetime.weekday(): segunda=0 ... domingo=6
PYTHON_WEEKDAY_TO_DIA_SEMANA = {
    0: "SEGUNDA",
    1: "TERCA",
    2: "QUARTA",
    3: "QUINTA",
    4: "SEXTA",
    5: "SABADO",
    6: "DOMINGO",
}


def ensure_dirs() -> None:
    # Vale nos dois modos: no WEB, DATA_DIR já aponta para o diretório
    # temporário, que é gravável. Sem isto a exportação de PDF quebraria no ar,
    # porque o disco ao lado do código é somente-leitura em serverless.
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ESCALAS_DIR.mkdir(parents=True, exist_ok=True)
