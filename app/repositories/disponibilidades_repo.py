import sqlite3


def listar_slots_da_pessoa(conn: sqlite3.Connection, pessoa_id: int) -> list[str]:
    rows = conn.execute(
        "SELECT slot_id FROM disponibilidades WHERE pessoa_id = ? AND ativo = 1",
        (pessoa_id,),
    ).fetchall()
    return [r["slot_id"] for r in rows]


def listar_pessoas_do_slot(conn: sqlite3.Connection, slot_id: str) -> list[int]:
    rows = conn.execute(
        "SELECT pessoa_id FROM disponibilidades WHERE slot_id = ? AND ativo = 1",
        (slot_id,),
    ).fetchall()
    return [r["pessoa_id"] for r in rows]


def mapa_slot_para_pessoas(conn: sqlite3.Connection) -> dict[str, set[int]]:
    rows = conn.execute("SELECT slot_id, pessoa_id FROM disponibilidades WHERE ativo = 1").fetchall()
    mapa: dict[str, set[int]] = {}
    for r in rows:
        mapa.setdefault(r["slot_id"], set()).add(r["pessoa_id"])
    return mapa


def definir_disponibilidade_da_pessoa(conn: sqlite3.Connection, pessoa_id: int, slot_ids: list[str]) -> None:
    conn.execute("DELETE FROM disponibilidades WHERE pessoa_id = ?", (pessoa_id,))
    conn.executemany(
        "INSERT INTO disponibilidades (pessoa_id, slot_id, ativo) VALUES (?, ?, 1)",
        [(pessoa_id, slot_id) for slot_id in slot_ids],
    )
