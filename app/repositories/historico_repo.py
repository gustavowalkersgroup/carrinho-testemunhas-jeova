import sqlite3
from datetime import date

from app.models import DesignacaoCarrinho, DesignacaoDirigente, DesignacaoSaida


def _row_to_designacao(row: sqlite3.Row) -> DesignacaoCarrinho:
    return DesignacaoCarrinho(
        id=row["id"],
        data=row["data"],
        slot_id=row["slot_id"],
        pessoa_id_1=row["pessoa_id_1"],
        pessoa_id_2=row["pessoa_id_2"],
        origem=row["origem"],
        mes_referencia=row["mes_referencia"],
        status=row["status"],
    )


def _row_to_designacao_dirigente(row: sqlite3.Row) -> DesignacaoDirigente:
    return DesignacaoDirigente(
        id=row["id"],
        data=row["data"],
        slot_id=row["slot_id"],
        dirigente_id=row["dirigente_id"],
        mes_referencia=row["mes_referencia"],
        status=row["status"],
    )


# --- carrinho -------------------------------------------------------------

def ultima_designacao_por_pessoa(conn: sqlite3.Connection) -> dict[int, str]:
    """Data (isoformat) da designação FECHADA mais recente de cada pessoa."""
    rows = conn.execute(
        """
        SELECT pessoa_id, MAX(data) as ultima FROM (
            SELECT pessoa_id_1 AS pessoa_id, data FROM historico_carrinho
                WHERE status = 'FECHADO' AND pessoa_id_1 IS NOT NULL
            UNION ALL
            SELECT pessoa_id_2 AS pessoa_id, data FROM historico_carrinho
                WHERE status = 'FECHADO' AND pessoa_id_2 IS NOT NULL
        )
        GROUP BY pessoa_id
        """
    ).fetchall()
    return {r["pessoa_id"]: r["ultima"] for r in rows}


def total_designacoes_por_pessoa(conn: sqlite3.Connection) -> dict[int, int]:
    rows = conn.execute(
        """
        SELECT pessoa_id, COUNT(*) as total FROM (
            SELECT pessoa_id_1 AS pessoa_id FROM historico_carrinho
                WHERE status = 'FECHADO' AND pessoa_id_1 IS NOT NULL
            UNION ALL
            SELECT pessoa_id_2 AS pessoa_id FROM historico_carrinho
                WHERE status = 'FECHADO' AND pessoa_id_2 IS NOT NULL
        )
        GROUP BY pessoa_id
        """
    ).fetchall()
    return {r["pessoa_id"]: r["total"] for r in rows}


def duplas_recentes(conn: sqlite3.Connection, data_limite: date) -> set[frozenset[int]]:
    rows = conn.execute(
        """
        SELECT pessoa_id_1, pessoa_id_2 FROM historico_carrinho
        WHERE status = 'FECHADO' AND data >= ?
          AND pessoa_id_1 IS NOT NULL AND pessoa_id_2 IS NOT NULL
        """,
        (data_limite.isoformat(),),
    ).fetchall()
    return {frozenset((r["pessoa_id_1"], r["pessoa_id_2"])) for r in rows}


def inserir_lote(conn: sqlite3.Connection, designacoes: list[DesignacaoCarrinho]) -> None:
    conn.executemany(
        """
        INSERT INTO historico_carrinho
            (data, slot_id, pessoa_id_1, pessoa_id_2, origem, mes_referencia, status)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                d.data.isoformat(),
                d.slot_id,
                d.pessoa_id_1,
                d.pessoa_id_2,
                d.origem.value,
                d.mes_referencia,
                d.status.value,
            )
            for d in designacoes
        ],
    )


def deletar_rascunho_do_mes(conn: sqlite3.Connection, mes_referencia: str) -> None:
    conn.execute(
        "DELETE FROM historico_carrinho WHERE mes_referencia = ? AND status = 'RASCUNHO'",
        (mes_referencia,),
    )


def buscar_por_mes(conn: sqlite3.Connection, mes_referencia: str) -> list[DesignacaoCarrinho]:
    rows = conn.execute(
        "SELECT * FROM historico_carrinho WHERE mes_referencia = ? ORDER BY data",
        (mes_referencia,),
    ).fetchall()
    return [_row_to_designacao(r) for r in rows]


def atualizar_designacao(
    conn: sqlite3.Connection,
    designacao_id: int,
    pessoa_id_1: int | None,
    pessoa_id_2: int | None,
) -> bool:
    cur = conn.execute(
        """
        UPDATE historico_carrinho
        SET pessoa_id_1 = ?, pessoa_id_2 = ?, origem = 'MANUAL'
        WHERE id = ? AND status = 'RASCUNHO'
        """,
        (pessoa_id_1, pessoa_id_2, designacao_id),
    )
    return cur.rowcount > 0


def fechar_mes(conn: sqlite3.Connection, mes_referencia: str) -> None:
    conn.execute(
        "UPDATE historico_carrinho SET status = 'FECHADO' WHERE mes_referencia = ? AND status = 'RASCUNHO'",
        (mes_referencia,),
    )


# --- dirigentes -------------------------------------------------------------

def ultima_designacao_por_dirigente(conn: sqlite3.Connection) -> dict[int, str]:
    rows = conn.execute(
        """
        SELECT dirigente_id, MAX(data) as ultima FROM historico_dirigentes
        WHERE status = 'FECHADO' AND dirigente_id IS NOT NULL
        GROUP BY dirigente_id
        """
    ).fetchall()
    return {r["dirigente_id"]: r["ultima"] for r in rows}


def total_designacoes_por_dirigente(conn: sqlite3.Connection) -> dict[int, int]:
    rows = conn.execute(
        """
        SELECT dirigente_id, COUNT(*) as total FROM historico_dirigentes
        WHERE status = 'FECHADO' AND dirigente_id IS NOT NULL
        GROUP BY dirigente_id
        """
    ).fetchall()
    return {r["dirigente_id"]: r["total"] for r in rows}


def inserir_lote_dirigentes(conn: sqlite3.Connection, designacoes: list[DesignacaoDirigente]) -> None:
    conn.executemany(
        """
        INSERT INTO historico_dirigentes (data, slot_id, dirigente_id, mes_referencia, status)
        VALUES (?, ?, ?, ?, ?)
        """,
        [
            (d.data.isoformat(), d.slot_id, d.dirigente_id, d.mes_referencia, d.status.value)
            for d in designacoes
        ],
    )


def deletar_rascunho_dirigentes_do_mes(conn: sqlite3.Connection, mes_referencia: str) -> None:
    conn.execute(
        "DELETE FROM historico_dirigentes WHERE mes_referencia = ? AND status = 'RASCUNHO'",
        (mes_referencia,),
    )


def buscar_dirigentes_por_mes(conn: sqlite3.Connection, mes_referencia: str) -> list[DesignacaoDirigente]:
    rows = conn.execute(
        "SELECT * FROM historico_dirigentes WHERE mes_referencia = ? ORDER BY data",
        (mes_referencia,),
    ).fetchall()
    return [_row_to_designacao_dirigente(r) for r in rows]


def atualizar_designacao_dirigente(conn: sqlite3.Connection, designacao_id: int, dirigente_id: int | None) -> bool:
    cur = conn.execute(
        "UPDATE historico_dirigentes SET dirigente_id = ? WHERE id = ? AND status = 'RASCUNHO'",
        (dirigente_id, designacao_id),
    )
    return cur.rowcount > 0


def fechar_mes_dirigentes(conn: sqlite3.Connection, mes_referencia: str) -> None:
    conn.execute(
        "UPDATE historico_dirigentes SET status = 'FECHADO' WHERE mes_referencia = ? AND status = 'RASCUNHO'",
        (mes_referencia,),
    )


# --- saída de campo ---------------------------------------------------------

def _row_to_designacao_saida(row: sqlite3.Row) -> DesignacaoSaida:
    return DesignacaoSaida(
        id=row["id"],
        data=row["data"],
        saida_id=row["saida_id"],
        dirigente_id=row["dirigente_id"],
        mes_referencia=row["mes_referencia"],
        status=row["status"],
    )


def ultima_saida_por_dirigente(conn: sqlite3.Connection) -> dict[int, str]:
    rows = conn.execute(
        """
        SELECT dirigente_id, MAX(data) as ultima FROM historico_saidas
        WHERE status = 'FECHADO' AND dirigente_id IS NOT NULL
        GROUP BY dirigente_id
        """
    ).fetchall()
    return {r["dirigente_id"]: r["ultima"] for r in rows}


def total_saidas_por_dirigente(conn: sqlite3.Connection) -> dict[int, int]:
    rows = conn.execute(
        """
        SELECT dirigente_id, COUNT(*) as total FROM historico_saidas
        WHERE status = 'FECHADO' AND dirigente_id IS NOT NULL
        GROUP BY dirigente_id
        """
    ).fetchall()
    return {r["dirigente_id"]: r["total"] for r in rows}


def inserir_lote_saidas(conn: sqlite3.Connection, designacoes: list[DesignacaoSaida]) -> None:
    conn.executemany(
        """
        INSERT INTO historico_saidas (data, saida_id, dirigente_id, mes_referencia, status)
        VALUES (?, ?, ?, ?, ?)
        """,
        [
            (d.data.isoformat(), d.saida_id, d.dirigente_id, d.mes_referencia, d.status.value)
            for d in designacoes
        ],
    )


def deletar_rascunho_saidas_do_mes(conn: sqlite3.Connection, mes_referencia: str) -> None:
    conn.execute(
        "DELETE FROM historico_saidas WHERE mes_referencia = ? AND status = 'RASCUNHO'",
        (mes_referencia,),
    )


def buscar_saidas_por_mes(conn: sqlite3.Connection, mes_referencia: str) -> list[DesignacaoSaida]:
    rows = conn.execute(
        "SELECT * FROM historico_saidas WHERE mes_referencia = ? ORDER BY data",
        (mes_referencia,),
    ).fetchall()
    return [_row_to_designacao_saida(r) for r in rows]


def atualizar_designacao_saida(conn: sqlite3.Connection, designacao_id: int, dirigente_id: int | None) -> bool:
    cur = conn.execute(
        "UPDATE historico_saidas SET dirigente_id = ? WHERE id = ? AND status = 'RASCUNHO'",
        (dirigente_id, designacao_id),
    )
    return cur.rowcount > 0


def fechar_mes_saidas(conn: sqlite3.Connection, mes_referencia: str) -> None:
    conn.execute(
        "UPDATE historico_saidas SET status = 'FECHADO' WHERE mes_referencia = ? AND status = 'RASCUNHO'",
        (mes_referencia,),
    )
