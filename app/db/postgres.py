"""Adaptador Postgres com a mesma interface do módulo `sqlite3`.

O app nasceu como programa de desktop com SQLite e tem ~160 consultas escritas
em SQL cru, espalhadas pelos repositórios. Para rodar hospedado (Vercel, disco
efêmero e somente-leitura) o banco precisa ser Postgres — mas reescrever cada
consulta seria trocar código testado por código novo sem necessidade.

Então este módulo expõe um objeto de conexão que se comporta como
`sqlite3.Connection`: `execute` / `executemany` / `executescript` recebendo
`?` como marcador de parâmetro, devolvendo linhas indexáveis tanto por nome
(`row["nome"]`) quanto por posição (`row[0]`). Assim os repositórios rodam sem
alteração nos dois bancos.

O isolamento entre congregações NÃO é feito aqui e sim pelo próprio Postgres,
com Row Level Security (ver schema_pg.sql): a conexão declara em qual
congregação está trabalhando (`definir_congregacao`) e o banco filtra tudo. Se
a congregação não for declarada, as políticas não casam com nada e as consultas
voltam vazias — falha fechando, nunca vazando.
"""

from __future__ import annotations

import re
from contextlib import contextmanager
from typing import Any, Iterable, Optional, Sequence

import psycopg

from app import config

# `?` que não esteja dentro de aspas simples (literal SQL) nem duplas
# (identificador). Nenhuma consulta do projeto usa `?` literal, mas a regra
# evita corromper SQL que venha a usar — casa strings/identificadores primeiro
# e só troca o `?` que sobra fora deles.
_PLACEHOLDER = re.compile(r"'[^']*'|\"[^\"]*\"|\?")


def _traduzir_marcadores(sql: str) -> str:
    """`... WHERE id = ?` (SQLite) -> `... WHERE id = %s` (psycopg).

    Também escapa `%` literal, que em psycopg é o início de um marcador."""
    sql = sql.replace("%", "%%")
    return _PLACEHOLDER.sub(lambda m: "%s" if m.group(0) == "?" else m.group(0), sql)


class Row(Sequence):
    """Linha acessível por nome e por posição, como `sqlite3.Row`."""

    __slots__ = ("_valores", "_indices")

    def __init__(self, valores: tuple, indices: dict[str, int]):
        self._valores = valores
        self._indices = indices

    def __getitem__(self, chave):
        if isinstance(chave, str):
            try:
                return self._valores[self._indices[chave]]
            except KeyError:
                raise IndexError(f"coluna inexistente no resultado: {chave!r}") from None
        return self._valores[chave]

    def __len__(self) -> int:
        return len(self._valores)

    def __iter__(self):
        return iter(self._valores)

    def keys(self) -> list[str]:
        return list(self._indices)

    def __contains__(self, valor) -> bool:
        return valor in self._valores

    def __repr__(self) -> str:
        return f"Row({dict(zip(self._indices, self._valores))!r})"


def _fabrica_de_linhas(cursor):
    descricao = cursor.description
    if descricao is None:
        return lambda valores: valores
    indices = {col.name: i for i, col in enumerate(descricao)}
    return lambda valores: Row(valores, indices)


class Conexao:
    """Fachada sobre `psycopg.Connection` com a cara do `sqlite3.Connection`."""

    def __init__(self, conn: psycopg.Connection):
        self._conn = conn
        self.congregacao_id: Optional[int] = None
        self.super_admin: bool = False

    # --- interface estilo sqlite3 -----------------------------------------

    def execute(self, sql: str, params: Iterable[Any] = ()):
        cur = self._conn.cursor(row_factory=_fabrica_de_linhas)
        cur.execute(_traduzir_marcadores(sql), tuple(params))
        return cur

    def executemany(self, sql: str, seq_params: Iterable[Sequence[Any]]):
        linhas = [tuple(p) for p in seq_params]
        cur = self._conn.cursor(row_factory=_fabrica_de_linhas)
        if linhas:
            cur.executemany(_traduzir_marcadores(sql), linhas)
        return cur

    def executescript(self, sql: str):
        # psycopg aceita várias instruções num execute só quando não há
        # parâmetros; é exatamente o caso dos arquivos de schema.
        with self._conn.cursor() as cur:
            cur.execute(sql)
        return self

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def close(self) -> None:
        self._conn.close()

    # --- multi-tenant ------------------------------------------------------

    def definir_congregacao(self, congregacao_id: Optional[int]) -> None:
        """Declara para o Postgres em qual congregação esta transação trabalha.

        `is_local = true`: o valor vale só até o fim da transação, então uma
        conexão devolvida ao pool nunca leva o tenant anterior junto."""
        self.congregacao_id = congregacao_id
        valor = "" if congregacao_id is None else str(congregacao_id)
        self._conn.execute("SELECT set_config('app.congregacao_id', %s, true)", (valor,))

    def definir_super_admin(self, ativo: bool) -> None:
        """Libera leitura/escrita em todas as congregações.

        Só o painel do super-admin usa isso, e sempre depois de a sessão ter
        sido validada — nenhum dado vindo do navegador chega até aqui."""
        self.super_admin = ativo
        self._conn.execute(
            "SELECT set_config('app.super_admin', %s, true)", ("on" if ativo else "",)
        )

    # --- utilidades --------------------------------------------------------

    @property
    def bruta(self) -> psycopg.Connection:
        return self._conn

    def tabela_existe(self, nome: str) -> bool:
        row = self.execute(
            "SELECT 1 FROM information_schema.tables WHERE table_schema = current_schema() AND table_name = ?",
            (nome,),
        ).fetchone()
        return row is not None

    def colunas(self, tabela: str) -> set[str]:
        rows = self.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = ?",
            (tabela,),
        ).fetchall()
        return {r[0] for r in rows}

    def travar(self, chave: int) -> None:
        """Lock consultivo de transação: serializa as migrações quando várias
        instâncias serverless sobem ao mesmo tempo. Liberado no commit."""
        self._conn.execute("SELECT pg_advisory_xact_lock(%s)", (chave,))


def conectar() -> Conexao:
    conn = psycopg.connect(
        config.DATABASE_URL,
        autocommit=False,
        # Serverless abre e fecha conexão a cada request; sem timeout, uma
        # instabilidade de rede deixaria a função pendurada até o limite da
        # plataforma em vez de devolver erro rápido.
        connect_timeout=10,
    )
    return Conexao(conn)


@contextmanager
def get_connection(congregacao_id: Optional[int] = None, super_admin: bool = False):
    conn = conectar()
    try:
        if super_admin:
            conn.definir_super_admin(True)
        conn.definir_congregacao(congregacao_id)
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


__all__ = ["Conexao", "Row", "conectar", "get_connection"]
