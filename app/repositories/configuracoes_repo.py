import sqlite3
from typing import Optional


def obter(conn: sqlite3.Connection, chave: str, default: Optional[str] = None) -> Optional[str]:
    row = conn.execute("SELECT valor FROM configuracoes WHERE chave = ?", (chave,)).fetchone()
    return row["valor"] if row else default


def definir(conn: sqlite3.Connection, chave: str, valor: str) -> None:
    # UPDATE-depois-INSERT em vez de ON CONFLICT: a chave primária difere entre
    # os dois bancos (só `chave` no SQLite do desktop, `(congregacao_id, chave)`
    # no Postgres), e ON CONFLICT exige nomear exatamente as colunas do índice
    # único. Duas instruções simples valem nos dois — e no Postgres o RLS já
    # restringe as linhas à congregação da transação.
    cur = conn.execute("UPDATE configuracoes SET valor = ? WHERE chave = ?", (valor, chave))
    if cur.rowcount == 0:
        conn.execute("INSERT INTO configuracoes (chave, valor) VALUES (?, ?)", (chave, valor))


def obter_todas(conn: sqlite3.Connection) -> dict[str, str]:
    return {r["chave"]: r["valor"] for r in conn.execute("SELECT chave, valor FROM configuracoes")}
