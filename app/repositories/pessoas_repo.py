import sqlite3
from typing import Optional

from app.models import Pessoa, PessoaIn


def _row_to_pessoa(row: sqlite3.Row) -> Pessoa:
    return Pessoa(
        id=row["id"],
        nome=row["nome"],
        genero=row["genero"],
        ativo=bool(row["ativo"]),
        telefone=row["telefone"],
        observacoes=row["observacoes"],
        conjuge_id=row["conjuge_id"],
        pode_dirigir=bool(row["pode_dirigir"]),
    )


def listar(conn: sqlite3.Connection, somente_ativos: bool = False) -> list[Pessoa]:
    query = "SELECT * FROM pessoas"
    if somente_ativos:
        query += " WHERE ativo = 1"
    query += " ORDER BY nome"
    rows = conn.execute(query).fetchall()
    return [_row_to_pessoa(r) for r in rows]


def listar_dirigentes(conn: sqlite3.Connection, somente_ativos: bool = True) -> list[Pessoa]:
    """Pool de dirigentes = pessoas com pode_dirigir = 1 (e ativo = 1 se somente_ativos)."""
    query = "SELECT * FROM pessoas WHERE pode_dirigir = 1"
    if somente_ativos:
        query += " AND ativo = 1"
    query += " ORDER BY nome"
    rows = conn.execute(query).fetchall()
    return [_row_to_pessoa(r) for r in rows]


def obter(conn: sqlite3.Connection, pessoa_id: int) -> Optional[Pessoa]:
    row = conn.execute("SELECT * FROM pessoas WHERE id = ?", (pessoa_id,)).fetchone()
    return _row_to_pessoa(row) if row else None


def criar(conn: sqlite3.Connection, pessoa: PessoaIn) -> Pessoa:
    cur = conn.execute(
        """
        INSERT INTO pessoas (nome, genero, ativo, telefone, observacoes, conjuge_id, pode_dirigir)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (pessoa.nome, pessoa.genero.value, int(pessoa.ativo), pessoa.telefone, pessoa.observacoes, pessoa.conjuge_id, int(pessoa.pode_dirigir)),
    )
    return Pessoa(id=cur.lastrowid, **pessoa.model_dump())


def atualizar(conn: sqlite3.Connection, pessoa_id: int, pessoa: PessoaIn) -> Optional[Pessoa]:
    cur = conn.execute(
        """
        UPDATE pessoas SET nome = ?, genero = ?, ativo = ?, telefone = ?, observacoes = ?, conjuge_id = ?, pode_dirigir = ?
        WHERE id = ?
        """,
        (pessoa.nome, pessoa.genero.value, int(pessoa.ativo), pessoa.telefone, pessoa.observacoes, pessoa.conjuge_id, int(pessoa.pode_dirigir), pessoa_id),
    )
    if cur.rowcount == 0:
        return None
    return Pessoa(id=pessoa_id, **pessoa.model_dump())


def inativar(conn: sqlite3.Connection, pessoa_id: int) -> bool:
    cur = conn.execute("UPDATE pessoas SET ativo = 0 WHERE id = ?", (pessoa_id,))
    return cur.rowcount > 0


def set_conjuge(conn: sqlite3.Connection, pessoa_id: int, conjuge_id: Optional[int]) -> bool:
    # Seta um lado so; a simetria e responsabilidade do cadastro_service.
    # conjuge_id None limpa o vinculo.
    cur = conn.execute(
        "UPDATE pessoas SET conjuge_id = ? WHERE id = ?",
        (conjuge_id, pessoa_id),
    )
    return cur.rowcount > 0
