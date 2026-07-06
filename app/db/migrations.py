import csv
import sqlite3

from app.config import SCHEMA_PATH, SEEDS_DIR
from app.db.connection import get_connection
from app.repositories import configuracoes_repo


def run_migrations() -> None:
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        schema_sql = f.read()

    with get_connection() as conn:
        conn.executescript(schema_sql)
        _garantir_colunas(conn)
        _migrar_dirigentes_para_pessoas(conn)
        _seed_slot_template_if_empty(conn)
        _seed_saida_template_if_empty(conn)
        _seed_configuracoes_padrao(conn)


def _seed_configuracoes_padrao(conn) -> None:
    """Defaults idempotentes. Bancos que já têm pessoas cadastradas (instalações
    existentes) marcam o assistente inicial como já concluído — não interrompe
    quem já está usando o sistema. Bancos novos (0 pessoas) mostram o assistente."""
    existentes = {r["chave"] for r in conn.execute("SELECT chave FROM configuracoes")}
    tem_dados = conn.execute("SELECT COUNT(*) FROM pessoas").fetchone()[0] > 0
    if "idioma" not in existentes:
        configuracoes_repo.definir(conn, "idioma", "pt-BR")
    if "wizard_concluido" not in existentes:
        configuracoes_repo.definir(conn, "wizard_concluido", "1" if tem_dados else "0")
    if "nome_congregacao" not in existentes and tem_dados:
        configuracoes_repo.definir(conn, "nome_congregacao", "Carrinho — Parque das Nações")


def _garantir_colunas(conn: sqlite3.Connection) -> None:
    """CREATE TABLE IF NOT EXISTS não altera tabelas já existentes; para bancos
    criados antes de uma coluna nova, adiciona-a de forma idempotente."""
    colunas_pessoas = {row["name"] for row in conn.execute("PRAGMA table_info(pessoas)")}
    if "conjuge_id" not in colunas_pessoas:
        conn.execute("ALTER TABLE pessoas ADD COLUMN conjuge_id INTEGER REFERENCES pessoas(id)")
    if "pode_dirigir" not in colunas_pessoas:
        conn.execute("ALTER TABLE pessoas ADD COLUMN pode_dirigir INTEGER NOT NULL DEFAULT 0")


def _migrar_dirigentes_para_pessoas(conn: sqlite3.Connection) -> None:
    """Modelo novo: dirigente É uma pessoa (flag pode_dirigir). Migra a tabela
    legada `dirigentes` uma única vez: casa por primeiro nome com uma pessoa
    existente (marca pode_dirigir=1); sem correspondente único, cria uma pessoa
    nova (gênero M, sem disponibilidade de carrinho — não entra no sorteio do
    carrinho). Idempotente: não roda se já há alguém com pode_dirigir=1."""
    tabelas = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "dirigentes" not in tabelas:
        return
    if conn.execute("SELECT COUNT(*) FROM pessoas WHERE pode_dirigir = 1").fetchone()[0] > 0:
        return
    dirigentes = conn.execute("SELECT nome, ativo FROM dirigentes").fetchall()
    if not dirigentes:
        return

    pessoas_por_primeiro: dict[str, list[int]] = {}
    for r in conn.execute("SELECT id, nome FROM pessoas"):
        primeiro = r["nome"].split()[0]
        pessoas_por_primeiro.setdefault(primeiro, []).append(r["id"])

    for d in dirigentes:
        primeiro = d["nome"].split()[0]
        candidatos = pessoas_por_primeiro.get(primeiro, [])
        if len(candidatos) == 1:
            conn.execute("UPDATE pessoas SET pode_dirigir = 1 WHERE id = ?", (candidatos[0],))
        else:
            # sem correspondente único → cria pessoa dirigente (M), sem disponibilidade
            # de carrinho, então não é sorteada no carrinho; só atua como dirigente.
            conn.execute(
                "INSERT INTO pessoas (nome, genero, ativo, pode_dirigir) VALUES (?, 'M', ?, 1)",
                (d["nome"], d["ativo"]),
            )


def _seed_saida_template_if_empty(conn: sqlite3.Connection) -> None:
    """Default configurável: 1 saída de campo pela manhã, de segunda a sábado.
    O usuário ajusta na tela 'Saídas de Campo'."""
    if conn.execute("SELECT COUNT(*) FROM saida_campo_template").fetchone()[0] > 0:
        return
    dias = [
        ("SEGUNDA", "SEG"), ("TERCA", "TER"), ("QUARTA", "QUA"),
        ("QUINTA", "QUI"), ("SEXTA", "SEX"), ("SABADO", "SAB"),
    ]
    rows = [
        (f"{sig}_MANHA_SAIDA", dia, "MANHA", "", 1, "2020-01-01", None, 1)
        for dia, sig in dias
    ]
    conn.executemany(
        """
        INSERT INTO saida_campo_template
            (saida_id, dia_semana, periodo, local, ordem, vigencia_inicio, vigencia_fim, ativo)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )


def _seed_slot_template_if_empty(conn: sqlite3.Connection) -> None:
    count = conn.execute("SELECT COUNT(*) FROM slot_template").fetchone()[0]
    if count > 0:
        return

    seed_path = SEEDS_DIR / "slot_template_padrao.csv"
    with open(seed_path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = [
            (
                row["slot_id"],
                row["dia_semana"],
                row["periodo"],
                row["local"],
                int(row["ordem"]),
                int(row["requer_dirigente"]),
                row["vigencia_inicio"],
                row["vigencia_fim"] or None,
                int(row["ativo"]),
            )
            for row in reader
        ]

    conn.executemany(
        """
        INSERT INTO slot_template
            (slot_id, dia_semana, periodo, local, ordem, requer_dirigente,
             vigencia_inicio, vigencia_fim, ativo)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
