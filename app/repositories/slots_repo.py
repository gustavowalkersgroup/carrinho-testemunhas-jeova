import sqlite3
from datetime import date
from typing import Optional

from app.models import SlotTipo, SlotTipoIn


def _row_to_slot(row: sqlite3.Row) -> SlotTipo:
    return SlotTipo(
        slot_id=row["slot_id"],
        dia_semana=row["dia_semana"],
        periodo=row["periodo"],
        local=row["local"],
        ordem=row["ordem"],
        requer_dirigente=bool(row["requer_dirigente"]),
        vigencia_inicio=row["vigencia_inicio"],
        vigencia_fim=row["vigencia_fim"],
        ativo=bool(row["ativo"]),
    )


def listar(conn: sqlite3.Connection, somente_ativos: bool = False) -> list[SlotTipo]:
    query = "SELECT * FROM slot_template"
    if somente_ativos:
        query += " WHERE ativo = 1"
    query += " ORDER BY ordem"
    rows = conn.execute(query).fetchall()
    return [_row_to_slot(r) for r in rows]


def listar_vigentes_no_mes(conn: sqlite3.Connection, referencia: date) -> list[SlotTipo]:
    ref = referencia.isoformat()
    rows = conn.execute(
        """
        SELECT * FROM slot_template
        WHERE ativo = 1
          AND vigencia_inicio <= ?
          AND (vigencia_fim IS NULL OR vigencia_fim >= ?)
        ORDER BY ordem
        """,
        (ref, ref),
    ).fetchall()
    return [_row_to_slot(r) for r in rows]


def obter(conn: sqlite3.Connection, slot_id: str) -> Optional[SlotTipo]:
    row = conn.execute("SELECT * FROM slot_template WHERE slot_id = ?", (slot_id,)).fetchone()
    return _row_to_slot(row) if row else None


def criar(conn: sqlite3.Connection, slot: SlotTipoIn) -> SlotTipo:
    conn.execute(
        """
        INSERT INTO slot_template
            (slot_id, dia_semana, periodo, local, ordem, requer_dirigente,
             vigencia_inicio, vigencia_fim, ativo)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            slot.slot_id,
            slot.dia_semana,
            slot.periodo.value,
            slot.local,
            slot.ordem,
            int(slot.requer_dirigente),
            slot.vigencia_inicio.isoformat(),
            slot.vigencia_fim.isoformat() if slot.vigencia_fim else None,
            int(slot.ativo),
        ),
    )
    return SlotTipo(**slot.model_dump())


def atualizar(conn: sqlite3.Connection, slot_id: str, slot: SlotTipoIn) -> Optional[SlotTipo]:
    cur = conn.execute(
        """
        UPDATE slot_template
        SET dia_semana = ?, periodo = ?, local = ?, ordem = ?, requer_dirigente = ?,
            vigencia_inicio = ?, vigencia_fim = ?, ativo = ?
        WHERE slot_id = ?
        """,
        (
            slot.dia_semana,
            slot.periodo.value,
            slot.local,
            slot.ordem,
            int(slot.requer_dirigente),
            slot.vigencia_inicio.isoformat(),
            slot.vigencia_fim.isoformat() if slot.vigencia_fim else None,
            int(slot.ativo),
            slot_id,
        ),
    )
    if cur.rowcount == 0:
        return None
    return SlotTipo(slot_id=slot_id, **slot.model_dump(exclude={"slot_id"}))
