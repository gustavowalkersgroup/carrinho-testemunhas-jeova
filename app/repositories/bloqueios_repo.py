import sqlite3
from datetime import date

from app.models import Bloqueio, BloqueioIn


def _row_to_bloqueio(row: sqlite3.Row) -> Bloqueio:
    return Bloqueio(
        bloqueio_id=row["bloqueio_id"],
        data_inicio=row["data_inicio"],
        data_fim=row["data_fim"],
        motivo=row["motivo"],
        ativo=bool(row["ativo"]),
    )


def listar(conn: sqlite3.Connection) -> list[Bloqueio]:
    rows = conn.execute("SELECT * FROM bloqueios ORDER BY data_inicio").fetchall()
    return [_row_to_bloqueio(r) for r in rows]


def listar_ativos_no_periodo(conn: sqlite3.Connection, inicio: date, fim: date) -> list[Bloqueio]:
    rows = conn.execute(
        """
        SELECT * FROM bloqueios
        WHERE ativo = 1 AND data_inicio <= ? AND data_fim >= ?
        """,
        (fim.isoformat(), inicio.isoformat()),
    ).fetchall()
    return [_row_to_bloqueio(r) for r in rows]


def criar(conn: sqlite3.Connection, bloqueio: BloqueioIn) -> Bloqueio:
    cur = conn.execute(
        "INSERT INTO bloqueios (data_inicio, data_fim, motivo, ativo) VALUES (?, ?, ?, ?)",
        (
            bloqueio.data_inicio.isoformat(),
            bloqueio.data_fim.isoformat(),
            bloqueio.motivo,
            int(bloqueio.ativo),
        ),
    )
    return Bloqueio(bloqueio_id=cur.lastrowid, **bloqueio.model_dump())


def remover(conn: sqlite3.Connection, bloqueio_id: int) -> bool:
    cur = conn.execute("UPDATE bloqueios SET ativo = 0 WHERE bloqueio_id = ?", (bloqueio_id,))
    return cur.rowcount > 0
