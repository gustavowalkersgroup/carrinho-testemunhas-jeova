from datetime import date

import pytest

from app import config
from app.db.connection import get_connection
from app.repositories import disponibilidades_repo, pessoas_repo
from app.models import Genero, PessoaIn
from app.services import escala_service


@pytest.fixture
def conn_seed(tmp_path, monkeypatch):
    # Usa um DB real (com seed de slots) apontado para tmp_path, como em test_api_smoke.
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "carrinho.db")
    monkeypatch.setattr(config, "ESCALAS_DIR", tmp_path / "escalas")

    # dispara a criacao do app/DB (seed de slots) igual ao smoke test
    from app.main_api import create_app
    from fastapi.testclient import TestClient

    app = create_app()
    with TestClient(app):
        pass

    # get_connection e um @contextmanager (faz commit no exit)
    with get_connection() as connection:
        yield connection


def _preparar_mes(conn) -> str:
    slot_id = "SEG_TARDE_ZARGON"
    for nome in ["Ana", "Bruna", "Carla", "Diana"]:
        pid = pessoas_repo.criar(conn, PessoaIn(nome=nome, genero=Genero.F)).id
        disponibilidades_repo.definir_disponibilidade_da_pessoa(conn, pid, [slot_id])
    conn.commit()
    escala_service.gerar_rascunho(conn, 2026, 7, date(2026, 7, 1))
    conn.commit()
    return "2026-07"


def test_montar_dados_pdf_retorna_dados_coerentes(conn_seed):
    conn = conn_seed
    mes_referencia = _preparar_mes(conn)

    dados = escala_service.montar_dados_pdf(conn, 2026, 7)

    def _get(obj, chave):
        return obj[chave] if isinstance(obj, dict) else getattr(obj, chave)

    assert _get(dados, "mes_referencia") == mes_referencia

    caminho = _get(dados, "caminho")
    assert str(caminho).endswith(".pdf")
    assert mes_referencia in str(caminho)

    pessoas_por_id = _get(dados, "pessoas_por_id")
    assert isinstance(pessoas_por_id, dict)
    # todas as pessoas escaladas no mes devem aparecer no mapa de nomes
    escala = escala_service.obter_escala(conn, mes_referencia)
    ids_escalados = {
        pid
        for d in escala.designacoes
        for pid in (d.pessoa_id_1, d.pessoa_id_2)
        if pid is not None
    }
    assert ids_escalados  # o mes gerou designacoes
    assert ids_escalados.issubset(set(pessoas_por_id))

    dirigentes_por_id = _get(dados, "dirigentes_por_id")
    assert isinstance(dirigentes_por_id, dict)
