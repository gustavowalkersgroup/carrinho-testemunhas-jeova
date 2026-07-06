import sqlite3
from contextlib import contextmanager

from app import config


def _connect() -> sqlite3.Connection:
    # lê config.DB_PATH em cada chamada (em vez de `from app.config import DB_PATH`)
    # para que overrides em runtime/testes (monkeypatch de app.config.DB_PATH) tenham efeito
    config.ensure_dirs()
    # check_same_thread=False: em rotas `async def`, FastAPI resolve a dependência
    # get_conn numa thread do threadpool mas executa o handler no event loop —
    # a mesma conexão cruza threads (uso sempre sequencial, nunca concorrente).
    conn = sqlite3.connect(config.DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # WAL + busy_timeout: com abas/requests concorrentes, o modo journal padrão
    # trava leitura durante escrita e derruba a 2ª conexão com "database is locked" (500).
    # WAL permite leitores durante escrita; busy_timeout dá 5s de retry antes de falhar.
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


@contextmanager
def get_connection():
    conn = _connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
