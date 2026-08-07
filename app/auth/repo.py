"""Acesso às tabelas GLOBAIS: congregações, usuários, vínculos, solicitações,
sessões e códigos de login.

Estas tabelas não têm Row Level Security — elas não pertencem a nenhuma
congregação, e é justamente a partir delas que se descobre em qual congregação
a pessoa pode entrar. O controle de acesso aqui é feito pelo código
(`app/auth/service.py`), não pelo banco.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.auth.models import (
    Congregacao,
    Membro,
    Papel,
    Solicitacao,
    StatusSolicitacao,
    Usuario,
)


def agora() -> datetime:
    return datetime.now(timezone.utc)


# === Congregações ===========================================================

def _row_to_congregacao(row) -> Congregacao:
    return Congregacao(
        id=row["id"],
        nome=row["nome"],
        slug=row["slug"],
        cidade=row["cidade"],
        ativa=bool(row["ativa"]),
        criada_em=row["criada_em"],
    )


def gerar_slug(nome: str) -> str:
    """Nome da congregação -> identificador de URL. Sem acento, sem espaço."""
    sem_acento = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", sem_acento.lower()).strip("-")
    return slug[:48] or "congregacao"


def slug_disponivel(conn, slug: str) -> bool:
    return conn.execute("SELECT 1 FROM congregacoes WHERE slug = ?", (slug,)).fetchone() is None


def slug_unico(conn, nome: str) -> str:
    base = gerar_slug(nome)
    if slug_disponivel(conn, base):
        return base
    for n in range(2, 200):
        candidato = f"{base}-{n}"
        if slug_disponivel(conn, candidato):
            return candidato
    raise RuntimeError("não foi possível gerar um identificador único para a congregação")


def criar_congregacao(conn, nome: str, cidade: str = "") -> Congregacao:
    slug = slug_unico(conn, nome)
    row = conn.execute(
        "INSERT INTO congregacoes (nome, slug, cidade) VALUES (?, ?, ?) RETURNING *",
        (nome.strip(), slug, cidade.strip()),
    ).fetchone()
    return _row_to_congregacao(row)


def listar_congregacoes(conn, somente_ativas: bool = False) -> list[Congregacao]:
    query = "SELECT * FROM congregacoes"
    if somente_ativas:
        query += " WHERE ativa = 1"
    query += " ORDER BY nome"
    return [_row_to_congregacao(r) for r in conn.execute(query).fetchall()]


def obter_congregacao(conn, congregacao_id: int) -> Optional[Congregacao]:
    row = conn.execute("SELECT * FROM congregacoes WHERE id = ?", (congregacao_id,)).fetchone()
    return _row_to_congregacao(row) if row else None


def obter_congregacao_por_slug(conn, slug: str) -> Optional[Congregacao]:
    row = conn.execute("SELECT * FROM congregacoes WHERE slug = ?", (slug,)).fetchone()
    return _row_to_congregacao(row) if row else None


def renomear_congregacao(conn, congregacao_id: int, nome: str, cidade: str) -> bool:
    cur = conn.execute(
        "UPDATE congregacoes SET nome = ?, cidade = ? WHERE id = ?",
        (nome.strip(), cidade.strip(), congregacao_id),
    )
    return cur.rowcount > 0


def definir_congregacao_ativa(conn, congregacao_id: int, ativa: bool) -> bool:
    cur = conn.execute(
        "UPDATE congregacoes SET ativa = ? WHERE id = ?", (int(ativa), congregacao_id)
    )
    return cur.rowcount > 0


def remover_congregacao(conn, congregacao_id: int) -> bool:
    """Apaga a congregação E TODOS os seus dados (cascata no schema)."""
    cur = conn.execute("DELETE FROM congregacoes WHERE id = ?", (congregacao_id,))
    return cur.rowcount > 0


# === Usuários ===============================================================

def normalizar_email(email: str) -> str:
    return (email or "").strip().lower()


def _row_to_usuario(row) -> Usuario:
    return Usuario(
        id=row["id"],
        email=row["email"],
        nome=row["nome"],
        super_admin=bool(row["super_admin"]),
        ativo=bool(row["ativo"]),
        criado_em=row["criado_em"],
        ultimo_acesso_em=row["ultimo_acesso_em"],
    )


def obter_usuario_por_email(conn, email: str) -> Optional[Usuario]:
    row = conn.execute(
        "SELECT * FROM usuarios WHERE email = ?", (normalizar_email(email),)
    ).fetchone()
    return _row_to_usuario(row) if row else None


def obter_usuario(conn, usuario_id: int) -> Optional[Usuario]:
    row = conn.execute("SELECT * FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()
    return _row_to_usuario(row) if row else None


def criar_usuario(conn, email: str, nome: str = "", super_admin: bool = False) -> Usuario:
    row = conn.execute(
        "INSERT INTO usuarios (email, nome, super_admin) VALUES (?, ?, ?) RETURNING *",
        (normalizar_email(email), nome.strip(), int(super_admin)),
    ).fetchone()
    return _row_to_usuario(row)


def obter_ou_criar_usuario(conn, email: str, nome: str = "") -> Usuario:
    usuario = obter_usuario_por_email(conn, email)
    if usuario:
        if nome and not usuario.nome:
            conn.execute("UPDATE usuarios SET nome = ? WHERE id = ?", (nome.strip(), usuario.id))
            usuario.nome = nome.strip()
        return usuario
    return criar_usuario(conn, email, nome)


def listar_usuarios(conn) -> list[Usuario]:
    return [_row_to_usuario(r) for r in conn.execute("SELECT * FROM usuarios ORDER BY email")]


def definir_super_admin(conn, usuario_id: int, super_admin: bool) -> bool:
    cur = conn.execute(
        "UPDATE usuarios SET super_admin = ? WHERE id = ?", (int(super_admin), usuario_id)
    )
    return cur.rowcount > 0


def definir_usuario_ativo(conn, usuario_id: int, ativo: bool) -> bool:
    cur = conn.execute("UPDATE usuarios SET ativo = ? WHERE id = ?", (int(ativo), usuario_id))
    if not ativo:
        # bloquear alguém tem de derrubar as sessões abertas na hora, senão a
        # aba que já estava aberta continua funcionando até o cookie expirar.
        conn.execute("DELETE FROM sessoes WHERE usuario_id = ?", (usuario_id,))
    return cur.rowcount > 0


def registrar_acesso(conn, usuario_id: int) -> None:
    conn.execute("UPDATE usuarios SET ultimo_acesso_em = ? WHERE id = ?", (agora(), usuario_id))


def contar_super_admins(conn) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM usuarios WHERE super_admin = 1 AND ativo = 1"
    ).fetchone()[0]


# === Vínculos usuário <-> congregação =======================================

def _row_to_membro(row) -> Membro:
    return Membro(
        usuario_id=row["usuario_id"],
        congregacao_id=row["congregacao_id"],
        papel=Papel(row["papel"]),
        congregacao_nome=row["congregacao_nome"] if "congregacao_nome" in row.keys() else "",
        congregacao_slug=row["congregacao_slug"] if "congregacao_slug" in row.keys() else "",
    )


def listar_membros_do_usuario(conn, usuario_id: int) -> list[Membro]:
    rows = conn.execute(
        """
        SELECT m.usuario_id, m.congregacao_id, m.papel,
               c.nome AS congregacao_nome, c.slug AS congregacao_slug
        FROM membros m
        JOIN congregacoes c ON c.id = m.congregacao_id
        WHERE m.usuario_id = ? AND c.ativa = 1
        ORDER BY c.nome
        """,
        (usuario_id,),
    ).fetchall()
    return [_row_to_membro(r) for r in rows]


def listar_membros_da_congregacao(conn, congregacao_id: int) -> list[tuple[Usuario, Papel]]:
    rows = conn.execute(
        """
        SELECT u.*, m.papel
        FROM membros m
        JOIN usuarios u ON u.id = m.usuario_id
        WHERE m.congregacao_id = ?
        ORDER BY u.email
        """,
        (congregacao_id,),
    ).fetchall()
    return [(_row_to_usuario(r), Papel(r["papel"])) for r in rows]


def obter_papel(conn, usuario_id: int, congregacao_id: int) -> Optional[Papel]:
    row = conn.execute(
        "SELECT papel FROM membros WHERE usuario_id = ? AND congregacao_id = ?",
        (usuario_id, congregacao_id),
    ).fetchone()
    return Papel(row["papel"]) if row else None


def definir_membro(conn, usuario_id: int, congregacao_id: int, papel: Papel) -> None:
    cur = conn.execute(
        "UPDATE membros SET papel = ? WHERE usuario_id = ? AND congregacao_id = ?",
        (papel.value, usuario_id, congregacao_id),
    )
    if cur.rowcount == 0:
        conn.execute(
            "INSERT INTO membros (usuario_id, congregacao_id, papel) VALUES (?, ?, ?)",
            (usuario_id, congregacao_id, papel.value),
        )


def remover_membro(conn, usuario_id: int, congregacao_id: int) -> bool:
    cur = conn.execute(
        "DELETE FROM membros WHERE usuario_id = ? AND congregacao_id = ?",
        (usuario_id, congregacao_id),
    )
    # a sessão pode estar apontando para a congregação que acabou de ser
    # retirada; zerar aqui força o seletor a aparecer no próximo request.
    conn.execute(
        "UPDATE sessoes SET congregacao_id = NULL WHERE usuario_id = ? AND congregacao_id = ?",
        (usuario_id, congregacao_id),
    )
    return cur.rowcount > 0


def contar_admins_da_congregacao(conn, congregacao_id: int) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM membros WHERE congregacao_id = ? AND papel = 'ADMIN'",
        (congregacao_id,),
    ).fetchone()[0]


# === Solicitações de acesso =================================================

def _row_to_solicitacao(row) -> Solicitacao:
    chaves = row.keys()
    return Solicitacao(
        id=row["id"],
        email=row["email"],
        nome=row["nome"],
        congregacao_id=row["congregacao_id"],
        congregacao_nome_sugerida=row["congregacao_nome_sugerida"],
        congregacao_nome=(row["congregacao_nome"] or "") if "congregacao_nome" in chaves else "",
        mensagem=row["mensagem"],
        status=StatusSolicitacao(row["status"]),
        criada_em=row["criada_em"],
        decidida_em=row["decidida_em"],
        observacao_decisao=row["observacao_decisao"],
    )


def criar_solicitacao(
    conn,
    email: str,
    nome: str,
    congregacao_id: Optional[int],
    congregacao_nome_sugerida: str,
    mensagem: str,
) -> Optional[Solicitacao]:
    """Devolve None quando já existe um pedido pendente igual (índice único
    parcial no schema) — recarregar o formulário não deve gerar duplicata."""
    if solicitacao_pendente(conn, email, congregacao_id):
        return None
    row = conn.execute(
        """
        INSERT INTO solicitacoes_acesso
            (email, nome, congregacao_id, congregacao_nome_sugerida, mensagem)
        VALUES (?, ?, ?, ?, ?)
        RETURNING *
        """,
        (
            normalizar_email(email),
            nome.strip(),
            congregacao_id,
            congregacao_nome_sugerida.strip(),
            mensagem.strip()[:1000],
        ),
    ).fetchone()
    return _row_to_solicitacao(row)


def solicitacao_pendente(conn, email: str, congregacao_id: Optional[int]) -> bool:
    # Duas consultas em vez de uma com `? IS NULL`: o Postgres não consegue
    # inferir o tipo de um parâmetro solto num teste de nulidade e recusa a
    # instrução. Separar por caso evita o CAST e vale nos dois bancos.
    if congregacao_id is None:
        query = """
            SELECT 1 FROM solicitacoes_acesso
            WHERE email = ? AND status = 'PENDENTE' AND congregacao_id IS NULL
        """
        params = (normalizar_email(email),)
    else:
        query = """
            SELECT 1 FROM solicitacoes_acesso
            WHERE email = ? AND status = 'PENDENTE' AND congregacao_id = ?
        """
        params = (normalizar_email(email), congregacao_id)
    return conn.execute(query, params).fetchone() is not None


def listar_solicitacoes(
    conn, status: Optional[StatusSolicitacao] = None, congregacoes: Optional[list[int]] = None
) -> list[Solicitacao]:
    """`congregacoes` limita o resultado ao que um admin de congregação pode
    ver. `None` = sem limite (super-admin)."""
    query = """
        SELECT s.*, c.nome AS congregacao_nome
        FROM solicitacoes_acesso s
        LEFT JOIN congregacoes c ON c.id = s.congregacao_id
    """
    condicoes, params = [], []
    if status is not None:
        condicoes.append("s.status = ?")
        params.append(status.value)
    if congregacoes is not None:
        if not congregacoes:
            return []
        marcadores = ", ".join("?" for _ in congregacoes)
        condicoes.append(f"s.congregacao_id IN ({marcadores})")
        params.extend(congregacoes)
    if condicoes:
        query += " WHERE " + " AND ".join(condicoes)
    query += " ORDER BY s.criada_em DESC"
    return [_row_to_solicitacao(r) for r in conn.execute(query, params).fetchall()]


def obter_solicitacao(conn, solicitacao_id: int) -> Optional[Solicitacao]:
    row = conn.execute(
        """
        SELECT s.*, c.nome AS congregacao_nome
        FROM solicitacoes_acesso s
        LEFT JOIN congregacoes c ON c.id = s.congregacao_id
        WHERE s.id = ?
        """,
        (solicitacao_id,),
    ).fetchone()
    return _row_to_solicitacao(row) if row else None


def decidir_solicitacao(
    conn,
    solicitacao_id: int,
    status: StatusSolicitacao,
    decidida_por: int,
    observacao: str = "",
) -> bool:
    cur = conn.execute(
        """
        UPDATE solicitacoes_acesso
        SET status = ?, decidida_em = ?, decidida_por = ?, observacao_decisao = ?
        WHERE id = ? AND status = 'PENDENTE'
        """,
        (status.value, agora(), decidida_por, observacao.strip()[:500], solicitacao_id),
    )
    return cur.rowcount > 0


def contar_solicitacoes_recentes(conn) -> int:
    """Total de pedidos criados na última hora, de todo mundo. Usado para
    cortar o envio de avisos quando o formulário público está sendo abusado."""
    return conn.execute(
        "SELECT COUNT(*) FROM solicitacoes_acesso WHERE criada_em > ?",
        (agora() - timedelta(hours=1),),
    ).fetchone()[0]


def contar_solicitacoes_pendentes(conn, congregacoes: Optional[list[int]] = None) -> int:
    if congregacoes is None:
        return conn.execute(
            "SELECT COUNT(*) FROM solicitacoes_acesso WHERE status = 'PENDENTE'"
        ).fetchone()[0]
    if not congregacoes:
        return 0
    marcadores = ", ".join("?" for _ in congregacoes)
    return conn.execute(
        f"SELECT COUNT(*) FROM solicitacoes_acesso "
        f"WHERE status = 'PENDENTE' AND congregacao_id IN ({marcadores})",
        congregacoes,
    ).fetchone()[0]


# === Sessões ================================================================

def criar_sessao(
    conn, id_sessao: str, usuario_id: int, congregacao_id: Optional[int],
    duracao_dias: int, user_agent: str = "",
) -> None:
    conn.execute(
        """
        INSERT INTO sessoes (id, usuario_id, congregacao_id, expira_em, user_agent)
        VALUES (?, ?, ?, ?, ?)
        """,
        (id_sessao, usuario_id, congregacao_id, agora() + timedelta(days=duracao_dias),
         user_agent[:300]),
    )


def obter_sessao(conn, id_sessao: str):
    return conn.execute(
        "SELECT * FROM sessoes WHERE id = ? AND expira_em > ?", (id_sessao, agora())
    ).fetchone()


def trocar_congregacao_da_sessao(conn, id_sessao: str, congregacao_id: Optional[int]) -> None:
    conn.execute(
        "UPDATE sessoes SET congregacao_id = ? WHERE id = ?", (congregacao_id, id_sessao)
    )


def remover_sessao(conn, id_sessao: str) -> None:
    conn.execute("DELETE FROM sessoes WHERE id = ?", (id_sessao,))


def limpar_sessoes_expiradas(conn) -> None:
    conn.execute("DELETE FROM sessoes WHERE expira_em <= ?", (agora(),))


# === Códigos de login =======================================================

def criar_codigo(conn, email: str, codigo_hash: str, validade_minutos: int) -> None:
    conn.execute(
        "INSERT INTO codigos_login (email, codigo_hash, expira_em) VALUES (?, ?, ?)",
        (normalizar_email(email), codigo_hash, agora() + timedelta(minutes=validade_minutos)),
    )


def codigos_pedidos_na_ultima_hora(conn, email: str) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM codigos_login WHERE email = ? AND criado_em > ?",
        (normalizar_email(email), agora() - timedelta(hours=1)),
    ).fetchone()[0]


def obter_codigo_valido(conn, email: str):
    """Último código ainda válido (não usado, não expirado, com tentativas
    sobrando). Só o mais recente vale: pedir um novo invalida o anterior."""
    return conn.execute(
        """
        SELECT * FROM codigos_login
        WHERE email = ? AND usado_em IS NULL AND expira_em > ?
        ORDER BY criado_em DESC
        LIMIT 1
        """,
        (normalizar_email(email), agora()),
    ).fetchone()


def registrar_tentativa_errada(conn, codigo_id: int) -> None:
    conn.execute(
        "UPDATE codigos_login SET tentativas = tentativas + 1 WHERE id = ?", (codigo_id,)
    )


def marcar_codigo_usado(conn, codigo_id: int) -> None:
    conn.execute("UPDATE codigos_login SET usado_em = ? WHERE id = ?", (agora(), codigo_id))


def invalidar_codigos(conn, email: str) -> None:
    conn.execute(
        "UPDATE codigos_login SET usado_em = ? WHERE email = ? AND usado_em IS NULL",
        (agora(), normalizar_email(email)),
    )


def limpar_codigos_expirados(conn) -> None:
    conn.execute("DELETE FROM codigos_login WHERE expira_em <= ?", (agora() - timedelta(days=1),))
