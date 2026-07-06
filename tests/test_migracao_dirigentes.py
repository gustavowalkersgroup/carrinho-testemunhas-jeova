"""Testes da migração dirigentes->pessoas e do seed de saida_campo_template.

A migração roda dentro de run_migrations(), disparada ao criar o app (create_app)
com um DB tmp — mesmo padrão de test_escala_service.py / test_api_smoke.py.
Não rodar pytest aqui (edição paralela); apenas escrito.
"""
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app import config
from app.db.connection import get_connection


def _disparar_migracoes():
    """create_app + TestClient dispara run_migrations() uma vez (igual ao smoke)."""
    from app.main_api import create_app

    app = create_app()
    with TestClient(app):
        pass


@pytest.fixture
def db_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "carrinho.db")
    monkeypatch.setattr(config, "ESCALAS_DIR", tmp_path / "escalas")
    return tmp_path


def _contar(sql: str, params: tuple = ()) -> int:
    with get_connection() as conn:
        return conn.execute(sql, params).fetchone()[0]


def test_migracao_cria_pessoas_que_podem_dirigir(db_tmp):
    # O DB tmp começa vazio (sem tabela legada `dirigentes` populada), então a
    # migração de dirigentes->pessoas pode não criar ninguém automaticamente.
    # Semeamos um dirigente legado ANTES de migrar para exercitar o caminho real.
    from app.db.migrations import run_migrations

    # cria o schema uma primeira vez para poder inserir na tabela legada
    run_migrations()
    with get_connection() as conn:
        conn.execute("INSERT INTO dirigentes (nome, ativo) VALUES ('Fulano Sobrenome', 1)")
        conn.commit()

    # roda de novo: agora migra o dirigente legado para pessoas(pode_dirigir=1)
    run_migrations()

    assert _contar("SELECT COUNT(*) FROM pessoas WHERE pode_dirigir = 1") >= 1


def test_migracao_e_idempotente_nao_duplica_pessoas_nem_saidas(db_tmp):
    from app.db.migrations import run_migrations

    run_migrations()
    with get_connection() as conn:
        conn.execute("INSERT INTO dirigentes (nome, ativo) VALUES ('Fulano Sobrenome', 1)")
        conn.commit()

    run_migrations()
    pessoas_apos_1a = _contar("SELECT COUNT(*) FROM pessoas")
    saidas_apos_1a = _contar("SELECT COUNT(*) FROM saida_campo_template")

    # roda mais 2x: nada deve mudar (migração idempotente)
    run_migrations()
    run_migrations()

    assert _contar("SELECT COUNT(*) FROM pessoas") == pessoas_apos_1a
    assert _contar("SELECT COUNT(*) FROM saida_campo_template") == saidas_apos_1a


def test_seed_saida_campo_template_seg_a_sab_manha(db_tmp):
    _disparar_migracoes()

    with get_connection() as conn:
        rows = conn.execute(
            "SELECT dia_semana, periodo FROM saida_campo_template ORDER BY ordem, dia_semana"
        ).fetchall()

    assert len(rows) == 6  # segunda a sábado (sem domingo)
    dias = {r["dia_semana"] for r in rows}
    assert dias == {"SEGUNDA", "TERCA", "QUARTA", "QUINTA", "SEXTA", "SABADO"}
    assert all(r["periodo"] == "MANHA" for r in rows)


def test_seed_saida_nao_roda_2x(db_tmp):
    """Idempotência específica do seed de saídas via create_app disparado 2x."""
    _disparar_migracoes()
    total_1 = _contar("SELECT COUNT(*) FROM saida_campo_template")
    _disparar_migracoes()
    total_2 = _contar("SELECT COUNT(*) FROM saida_campo_template")
    assert total_1 == total_2 == 6
