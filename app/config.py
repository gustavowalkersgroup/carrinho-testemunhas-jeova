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


BASE_DIR = _resolve_base_dir()
DATA_DIR = BASE_DIR / "data"
ESCALAS_DIR = DATA_DIR / "escalas"
DB_PATH = DATA_DIR / "carrinho.db"

RESOURCES_DIR = _resolve_resources_dir()
APP_DIR = RESOURCES_DIR / "app"
SEEDS_DIR = APP_DIR / "seeds"
TEMPLATES_DIR = APP_DIR / "web" / "templates"
STATIC_DIR = APP_DIR / "web" / "static"
SCHEMA_PATH = APP_DIR / "db" / "schema.sql"

HOST = "127.0.0.1"
PORT = 8756

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
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ESCALAS_DIR.mkdir(parents=True, exist_ok=True)
