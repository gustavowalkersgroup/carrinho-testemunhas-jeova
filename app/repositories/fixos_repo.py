import sqlite3
from datetime import date
from typing import Optional

from app.models import Fixo, FixoIn


def _row_to_fixo(row: sqlite3.Row) -> Fixo:
    return Fixo(
        fixo_id=row["fixo_id"],
        slot_id=row["slot_id"],
        pessoa_id_1=row["pessoa_id_1"],
        pessoa_id_2=row["pessoa_id_2"],
        vigencia_inicio=row["vigencia_inicio"],
        vigencia_fim=row["vigencia_fim"],
        ativo=bool(row["ativo"]),
    )


def listar(conn: sqlite3.Connection) -> list[Fixo]:
    rows = conn.execute("SELECT * FROM fixos ORDER BY slot_id").fetchall()
    return [_row_to_fixo(r) for r in rows]


def listar_vigentes_no_mes(conn: sqlite3.Connection, referencia: date) -> list[Fixo]:
    ref = referencia.isoformat()
    rows = conn.execute(
        """
        SELECT * FROM fixos
        WHERE ativo = 1
          AND vigencia_inicio <= ?
          AND (vigencia_fim IS NULL OR vigencia_fim >= ?)
        """,
        (ref, ref),
    ).fetchall()
    return [_row_to_fixo(r) for r in rows]


def listar_vigentes_por_pessoa(
    conn: sqlite3.Connection,
    pessoa_id: int,
    vigencia_inicio: str,
    vigencia_fim: Optional[str] = None,
) -> list[Fixo]:
    # Fixos ativos que referenciam pessoa_id (como pessoa_id_1 OU pessoa_id_2)
    # e cujo periodo se sobrepoe a [vigencia_inicio, vigencia_fim].
    # Sobreposicao: a1 <= (b2 ou +inf) AND b1 <= (a2 ou +inf), fim None = aberto.
    # Datas em ISO string (consistente com o resto do repo).
    if vigencia_fim is None:
        # intervalo alvo aberto: sobrepoe se fixo nao terminou antes de vigencia_inicio
        query = """
            SELECT * FROM fixos
            WHERE ativo = 1
              AND (pessoa_id_1 = ? OR pessoa_id_2 = ?)
              AND (vigencia_fim IS NULL OR vigencia_fim >= ?)
        """
        params = (pessoa_id, pessoa_id, vigencia_inicio)
    else:
        query = """
            SELECT * FROM fixos
            WHERE ativo = 1
              AND (pessoa_id_1 = ? OR pessoa_id_2 = ?)
              AND vigencia_inicio <= ?
              AND (vigencia_fim IS NULL OR vigencia_fim >= ?)
        """
        params = (pessoa_id, pessoa_id, vigencia_fim, vigencia_inicio)
    rows = conn.execute(query, params).fetchall()
    return [_row_to_fixo(r) for r in rows]


def criar(conn: sqlite3.Connection, fixo: FixoIn) -> Fixo:
    cur = conn.execute(
        """
        INSERT INTO fixos (slot_id, pessoa_id_1, pessoa_id_2, vigencia_inicio, vigencia_fim, ativo)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            fixo.slot_id,
            fixo.pessoa_id_1,
            fixo.pessoa_id_2,
            fixo.vigencia_inicio.isoformat(),
            fixo.vigencia_fim.isoformat() if fixo.vigencia_fim else None,
            int(fixo.ativo),
        ),
    )
    return Fixo(fixo_id=cur.lastrowid, **fixo.model_dump())


def encerrar_vigencia(conn: sqlite3.Connection, fixo_id: int, data_fim: date) -> bool:
    cur = conn.execute(
        "UPDATE fixos SET vigencia_fim = ?, ativo = 0 WHERE fixo_id = ?",
        (data_fim.isoformat(), fixo_id),
    )
    return cur.rowcount > 0
