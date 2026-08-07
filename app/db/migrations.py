import csv
import sqlite3

from app import config
from app.config import SCHEMA_PATH, SCHEMA_PG_PATH, SEEDS_DIR
from app.db.connection import get_connection
from app.repositories import configuracoes_repo

# Sobe quando o schema muda de um jeito que exige reaplicar os arquivos .sql.
# No modo WEB isso evita reexecutar o schema inteiro a cada cold start da
# função serverless: uma consulta a `app_meta` resolve o caso comum.
SCHEMA_VERSAO = "3"

# Número arbitrário mas fixo: identifica o lock consultivo que serializa a
# migração quando várias instâncias serverless sobem ao mesmo tempo.
_LOCK_MIGRACAO = 8756_0001


def run_migrations() -> None:
    if config.MODO_WEB:
        _migrar_postgres()
    else:
        _migrar_sqlite()


# === Postgres (modo WEB) ====================================================

def _migrar_postgres() -> None:
    from app.db import postgres

    with postgres.get_connection(super_admin=True) as conn:
        if _schema_atualizado(conn):
            return
        # a partir daqui só uma instância por vez; o lock cai no commit
        conn.travar(_LOCK_MIGRACAO)
        if _schema_atualizado(conn):  # outra instância chegou antes e já migrou
            return
        with open(SCHEMA_PG_PATH, "r", encoding="utf-8") as f:
            conn.executescript(f.read())
        conn.execute(
            """
            INSERT INTO app_meta (chave, valor) VALUES ('schema_versao', ?)
            ON CONFLICT (chave) DO UPDATE SET valor = excluded.valor
            """,
            (SCHEMA_VERSAO,),
        )


def _schema_atualizado(conn) -> bool:
    if not conn.tabela_existe("app_meta"):
        return False
    row = conn.execute("SELECT valor FROM app_meta WHERE chave = 'schema_versao'").fetchone()
    return row is not None and row["valor"] == SCHEMA_VERSAO


def preparar_congregacao(conn, congregacao_id: int) -> None:
    """Popula uma congregação recém-criada com os padrões de fábrica.

    No desktop isso acontece na primeira execução (banco vazio); no modo WEB
    precisa acontecer uma vez por congregação, senão a congregação nova nasce
    sem nenhum horário e o assistente inicial não tem o que mostrar.

    O modo super-admin é desligado enquanto as sementes rodam: as três funções
    abaixo só semeiam quando a tabela está VAZIA, e com a visão global ligada
    elas enxergariam as linhas das outras congregações e concluiriam que não há
    nada a fazer — a congregação nova nasceria sem horário nenhum."""
    congregacao_anterior = conn.congregacao_id
    super_admin_anterior = conn.super_admin
    conn.definir_super_admin(False)
    conn.definir_congregacao(congregacao_id)
    try:
        _seed_slot_template_if_empty(conn)
        _seed_saida_template_if_empty(conn)
        _seed_configuracoes_padrao(conn)
    finally:
        conn.definir_congregacao(congregacao_anterior)
        conn.definir_super_admin(super_admin_anterior)


# === SQLite (modo LOCAL / desktop) ==========================================

def _migrar_sqlite() -> None:
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


# === Sementes compartilhadas ================================================

def _seed_saida_template_if_empty(conn) -> None:
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


def _seed_slot_template_if_empty(conn) -> None:
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
