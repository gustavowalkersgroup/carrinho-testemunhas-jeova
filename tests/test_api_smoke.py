from datetime import date

import pytest
from fastapi.testclient import TestClient

from app import config


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "carrinho.db")
    monkeypatch.setattr(config, "ESCALAS_DIR", tmp_path / "escalas")

    from app.main_api import create_app

    app = create_app()
    with TestClient(app) as c:
        yield c


def test_seed_de_slots_e_criado_no_primeiro_uso(client):
    resp = client.get("/api/slots")
    assert resp.status_code == 200
    slots = resp.json()
    assert len(slots) == 9
    assert any(s["slot_id"] == "QUA_CONDOMINIO" for s in slots)


def test_fluxo_completo_cadastro_e_geracao_de_escala(client):
    # cadastra pessoas suficientes (mesmo gênero) para o slot de segunda à tarde
    ids = []
    for nome in ["Ana", "Bruna", "Carla", "Diana"]:
        resp = client.post("/api/pessoas", json={"nome": nome, "genero": "F"})
        assert resp.status_code == 200
        ids.append(resp.json()["id"])

    slot_id = "SEG_TARDE_ZARGON"
    for pessoa_id in ids:
        resp = client.put(f"/api/disponibilidades/pessoa/{pessoa_id}", json={"slot_ids": [slot_id]})
        assert resp.status_code == 200

    resp = client.post("/api/escalas/2026/7/gerar")
    assert resp.status_code == 200
    escala = resp.json()
    assert escala["mes_referencia"] == "2026-07"

    designacoes_segunda = [d for d in escala["designacoes"] if d["slot_id"] == slot_id]
    assert len(designacoes_segunda) == 4  # 4 segundas em julho/2026
    for d in designacoes_segunda:
        assert d["pessoa_id_1"] in ids
        assert d["pessoa_id_2"] in ids
        assert d["pessoa_id_1"] != d["pessoa_id_2"]

    # edita manualmente uma designação
    alvo = designacoes_segunda[0]
    resp = client.put(
        f"/api/escalas/designacao/{alvo['id']}",
        json={"pessoa_id_1": ids[0], "pessoa_id_2": ids[1]},
    )
    assert resp.status_code == 200

    # fecha o mês
    resp = client.post("/api/escalas/2026-07/fechar")
    assert resp.status_code == 200

    resp = client.get("/api/escalas/2026-07")
    assert all(d["status"] == "FECHADO" for d in resp.json()["designacoes"])


def test_exportar_pdf_gera_arquivo(client):
    resp = client.post("/api/pessoas", json={"nome": "Ana", "genero": "F"})
    p1 = resp.json()["id"]
    resp = client.post("/api/pessoas", json={"nome": "Bruna", "genero": "F"})
    p2 = resp.json()["id"]
    for pid in (p1, p2):
        client.put(f"/api/disponibilidades/pessoa/{pid}", json={"slot_ids": ["SEG_TARDE_ZARGON"]})

    client.post("/api/escalas/2026/7/gerar")
    resp = client.get("/api/escalas/2026-07/pdf")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert len(resp.content) > 500


def test_web_ui_home_redireciona_para_assistente_quando_nao_configurado(client):
    # banco novo (0 pessoas) -> wizard_concluido="0" -> assistente inicial
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code in (302, 307)
    assert "/assistente" in resp.headers["location"]


def test_web_ui_home_redireciona_para_escala_quando_assistente_concluido(client):
    client.post("/assistente/concluir")
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code in (302, 307)
    assert "/escala" in resp.headers["location"]


def test_web_ui_pagina_pessoas_renderiza(client):
    client.post("/api/pessoas", json={"nome": "Ana", "genero": "F"})
    resp = client.get("/pessoas")
    assert resp.status_code == 200
    assert "Ana" in resp.text


def test_fixo_de_dupla_em_genero_misto_e_permitido(client):
    # exceção deliberada: um fixo é uma decisão explícita do administrador
    # (ex.: casal que sempre serve junto), diferente do sorteio aleatório,
    # que continua exigindo sempre o mesmo gênero.
    p1 = client.post("/api/pessoas", json={"nome": "Adelson", "genero": "M"}).json()["id"]
    p2 = client.post("/api/pessoas", json={"nome": "Cassilda", "genero": "F"}).json()["id"]
    resp = client.post("/api/fixos", json={
        "slot_id": "QUA_TARDE_ZARGON", "pessoa_id_1": p1, "pessoa_id_2": p2,
        "vigencia_inicio": "2026-01-01",
    })
    assert resp.status_code == 200
    assert resp.json()["pessoa_id_2"] == p2
