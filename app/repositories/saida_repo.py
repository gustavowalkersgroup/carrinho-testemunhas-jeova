import sqlite3
from datetime import date
from typing import Optional

from app.models import SaidaCampoTemplate, SaidaCampoTemplateIn


def _row_to_saida(row: sqlite3.Row) -> SaidaCampoTemplate:
    return SaidaCampoTemplate(
        saida_id=row["saida_id"],
        dia_semana=row["dia_semana"],
        periodo=row["periodo"],
        local=row["local"],
        ordem=row["ordem"],
        vigencia_inicio=row["vigencia_inicio"],
        vigencia_fim=row["vigencia_fim"],
        ativo=bool(row["ativo"]),
    )


def listar(conn: sqlite3.Connection, somente_ativos: bool = False) -> list[SaidaCampoTemplate]:
    query = "SELECT * FROM saida_campo_template"
    if somente_ativos:
        query += " WHERE ativo = 1"
    query += " ORDER BY ordem, saida_id"
    rows = conn.execute(query).fetchall()
    return [_row_to_saida(r) for r in rows]


def listar_vigentes_no_mes(conn: sqlite3.Connection, referencia: date) -> list[SaidaCampoTemplate]:
    ref = referencia.isoformat()
    rows = conn.execute(
        """
        SELECT * FROM saida_campo_template
        WHERE ativo = 1
          AND vigencia_inicio <= ?
          AND (vigencia_fim IS NULL OR vigencia_fim >= ?)
        ORDER BY ordem, saida_id
        """,
        (ref, ref),
    ).fetchall()
    return [_row_to_saida(r) for r in rows]


def obter(conn: sqlite3.Connection, saida_id: str) -> Optional[SaidaCampoTemplate]:
    row = conn.execute(
        "SELECT * FROM saida_campo_template WHERE saida_id = ?", (saida_id,)
    ).fetchone()
    return _row_to_saida(row) if row else None


def criar(conn: sqlite3.Connection, s: SaidaCampoTemplateIn) -> SaidaCampoTemplate:
    conn.execute(
        """
        INSERT INTO saida_campo_template
            (saida_id, dia_semana, periodo, local, ordem,
             vigencia_inicio, vigencia_fim, ativo)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            s.saida_id,
            s.dia_semana,
            s.periodo.value,
            s.local,
            s.ordem,
            s.vigencia_inicio.isoformat(),
            s.vigencia_fim.isoformat() if s.vigencia_fim else None,
            int(s.ativo),
        ),
    )
    return SaidaCampoTemplate(**s.model_dump())


def atualizar(
    conn: sqlite3.Connection, saida_id: str, s: SaidaCampoTemplateIn
) -> Optional[SaidaCampoTemplate]:
    cur = conn.execute(
        """
        UPDATE saida_campo_template
        SET dia_semana = ?, periodo = ?, local = ?, ordem = ?,
            vigencia_inicio = ?, vigencia_fim = ?, ativo = ?
        WHERE saida_id = ?
        """,
        (
            s.dia_semana,
            s.periodo.value,
            s.local,
            s.ordem,
            s.vigencia_inicio.isoformat(),
            s.vigencia_fim.isoformat() if s.vigencia_fim else None,
            int(s.ativo),
            saida_id,
        ),
    )
    if cur.rowcount == 0:
        return None
    return SaidaCampoTemplate(saida_id=saida_id, **s.model_dump(exclude={"saida_id"}))


# --- disponibilidade por saída --------------------------------------------

def listar_saidas_do_dirigente(conn: sqlite3.Connection, pessoa_id: int) -> list[str]:
    rows = conn.execute(
        "SELECT saida_id FROM saida_disponibilidade WHERE pessoa_id = ?",
        (pessoa_id,),
    ).fetchall()
    return [r["saida_id"] for r in rows]


def definir_disponibilidade_do_dirigente(
    conn: sqlite3.Connection, pessoa_id: int, saida_ids: list[str]
) -> None:
    conn.execute("DELETE FROM saida_disponibilidade WHERE pessoa_id = ?", (pessoa_id,))
    conn.executemany(
        "INSERT INTO saida_disponibilidade (pessoa_id, saida_id) VALUES (?, ?)",
        [(pessoa_id, saida_id) for saida_id in saida_ids],
    )


def mapa_saida_para_dirigentes(conn: sqlite3.Connection) -> dict[str, set[int]]:
    """Para cada saída ATIVA, conjunto de pessoa_ids (pode_dirigir=1, ativo=1) disponíveis.

    FALLBACK: dirigente sem NENHUMA linha em saida_disponibilidade é considerado
    disponível para TODAS as saídas ativas (espelha dirigentes_repo.mapa_slot_para_dirigentes)."""
    todos = {
        r["id"]
        for r in conn.execute(
            "SELECT id FROM pessoas WHERE pode_dirigir = 1 AND ativo = 1"
        ).fetchall()
    }
    rows = conn.execute("SELECT DISTINCT pessoa_id FROM saida_disponibilidade").fetchall()
    com_restricao = {r["pessoa_id"] for r in rows}
    sem_restricao = todos - com_restricao

    mapa: dict[str, set[int]] = {}
    for r in conn.execute("SELECT pessoa_id, saida_id FROM saida_disponibilidade").fetchall():
        if r["pessoa_id"] in todos:
            mapa.setdefault(r["saida_id"], set()).add(r["pessoa_id"])

    for row in conn.execute("SELECT saida_id FROM saida_campo_template WHERE ativo = 1").fetchall():
        mapa.setdefault(row["saida_id"], set()).update(sem_restricao)

    return mapa
