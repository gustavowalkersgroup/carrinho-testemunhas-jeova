import sqlite3
from typing import Optional


def obter(conn: sqlite3.Connection, chave: str, default: Optional[str] = None) -> Optional[str]:
    row = conn.execute("SELECT valor FROM configuracoes WHERE chave = ?", (chave,)).fetchone()
    return row["valor"] if row else default


def definir(conn: sqlite3.Connection, chave: str, valor: str) -> None:
    conn.execute(
        """
        INSERT INTO configuracoes (chave, valor) VALUES (?, ?)
        ON CONFLICT (chave) DO UPDATE SET valor = excluded.valor
        """,
        (chave, valor),
    )


def obter_todas(conn: sqlite3.Connection) -> dict[str, str]:
    return {r["chave"]: r["valor"] for r in conn.execute("SELECT chave, valor FROM configuracoes")}
