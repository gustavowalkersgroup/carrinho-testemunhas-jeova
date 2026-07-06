import sqlite3
from typing import Optional

from app.models import Dirigente, DirigenteIn


def _row_to_dirigente(row: sqlite3.Row) -> Dirigente:
    return Dirigente(id=row["id"], nome=row["nome"], ativo=bool(row["ativo"]))


def listar(conn: sqlite3.Connection, somente_ativos: bool = False) -> list[Dirigente]:
    query = "SELECT * FROM dirigentes"
    if somente_ativos:
        query += " WHERE ativo = 1"
    query += " ORDER BY nome"
    rows = conn.execute(query).fetchall()
    return [_row_to_dirigente(r) for r in rows]


def criar(conn: sqlite3.Connection, dirigente: DirigenteIn) -> Dirigente:
    cur = conn.execute(
        "INSERT INTO dirigentes (nome, ativo) VALUES (?, ?)",
        (dirigente.nome, int(dirigente.ativo)),
    )
    return Dirigente(id=cur.lastrowid, **dirigente.model_dump())


def atualizar(conn: sqlite3.Connection, dirigente_id: int, dirigente: DirigenteIn) -> Optional[Dirigente]:
    cur = conn.execute(
        "UPDATE dirigentes SET nome = ?, ativo = ? WHERE id = ?",
        (dirigente.nome, int(dirigente.ativo), dirigente_id),
    )
    if cur.rowcount == 0:
        return None
    return Dirigente(id=dirigente_id, **dirigente.model_dump())


def listar_slots_do_dirigente(conn: sqlite3.Connection, dirigente_id: int) -> list[str]:
    rows = conn.execute(
        "SELECT slot_id FROM dirigentes_disponibilidade WHERE dirigente_id = ?",
        (dirigente_id,),
    ).fetchall()
    return [r["slot_id"] for r in rows]


def definir_disponibilidade_do_dirigente(conn: sqlite3.Connection, dirigente_id: int, slot_ids: list[str]) -> None:
    conn.execute("DELETE FROM dirigentes_disponibilidade WHERE dirigente_id = ?", (dirigente_id,))
    conn.executemany(
        "INSERT INTO dirigentes_disponibilidade (dirigente_id, slot_id) VALUES (?, ?)",
        [(dirigente_id, slot_id) for slot_id in slot_ids],
    )


def mapa_slot_para_dirigentes(conn: sqlite3.Connection) -> dict[str, set[int]]:
    """Dirigentes sem nenhuma linha cadastrada são considerados disponíveis para
    todos os slots que exigem dirigente (regra de fallback documentada no plano)."""
    todos = {d.id for d in listar(conn, somente_ativos=True)}
    rows = conn.execute("SELECT DISTINCT dirigente_id FROM dirigentes_disponibilidade").fetchall()
    com_restricao = {r["dirigente_id"] for r in rows}
    sem_restricao = todos - com_restricao

    mapa: dict[str, set[int]] = {}
    for r in conn.execute("SELECT dirigente_id, slot_id FROM dirigentes_disponibilidade").fetchall():
        if r["dirigente_id"] in todos:
            mapa.setdefault(r["slot_id"], set()).add(r["dirigente_id"])

    for row in conn.execute("SELECT slot_id FROM slot_template WHERE requer_dirigente = 1").fetchall():
        mapa.setdefault(row["slot_id"], set()).update(sem_restricao)

    return mapa
