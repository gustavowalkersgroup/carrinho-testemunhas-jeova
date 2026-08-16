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


def test_pagina_pessoas_filtra_por_nome_genero_status_conjuge_e_dirigente(client):
    ana = client.post("/api/pessoas", json={"nome": "Ana Beatriz", "genero": "F"}).json()["id"]
    bruno = client.post("/api/pessoas", json={"nome": "Bruno", "genero": "M", "pode_dirigir": True}).json()["id"]
    carla = client.post("/api/pessoas", json={"nome": "Carla", "genero": "F"}).json()["id"]

    # checa pela presença do link de edição de cada um, não do nome cru: o
    # nome de uma pessoa aparece na linha de OUTRA como cônjuge dela, então
    # procurar a string do nome solto dá falso positivo/negativo.
    def _presentes(pagina):
        return {
            pid: f"/pessoas/{pid}/editar" in pagina.text
            for pid in (ana, bruno, carla)
        }

    client.post(f"/pessoas/{bruno}/editar", data={
        "nome": "Bruno", "genero": "M", "ativo": "on", "pode_dirigir": "on", "conjuge_id": str(ana),
    })
    client.post(f"/pessoas/{carla}/inativar")

    presentes = _presentes(client.get("/pessoas", params={"q": "ana"}))
    assert presentes[ana] and not presentes[bruno] and not presentes[carla]

    presentes = _presentes(client.get("/pessoas", params={"genero": "M"}))
    assert presentes[bruno] and not presentes[ana]

    presentes = _presentes(client.get("/pessoas", params={"status": "inativos"}))
    assert presentes[carla] and not presentes[ana] and not presentes[bruno]

    presentes = _presentes(client.get("/pessoas", params={"conjuge": "com"}))
    assert presentes[ana] and presentes[bruno] and not presentes[carla]

    presentes = _presentes(client.get("/pessoas", params={"conjuge": "sem"}))
    assert presentes[carla] and not presentes[ana] and not presentes[bruno]

    presentes = _presentes(client.get("/pessoas", params={"dirigente": "sim"}))
    assert presentes[bruno] and not presentes[ana]

    pagina = client.get("/pessoas", params={"q": "zzz-inexistente"})
    assert "Nenhuma pessoa encontrada" in pagina.text


def test_editar_pessoa_esconde_conjuge_ja_comprometido_mas_mantem_o_proprio(client):
    # cada pessoa so pode ter UM conjuge (ver cadastro_service.definir_conjuge):
    # a combobox de edicao precisa esconder quem ja esta casado com OUTRA
    # pessoa, senao o admin escolheria alguem comprometido sem perceber que
    # isso desfaz o casamento anterior dessa pessoa.
    a = client.post("/api/pessoas", json={"nome": "Adelson", "genero": "M"}).json()["id"]
    b = client.post("/api/pessoas", json={"nome": "Cassilda", "genero": "F"}).json()["id"]
    c = client.post("/api/pessoas", json={"nome": "Berenice", "genero": "F"}).json()["id"]
    d = client.post("/api/pessoas", json={"nome": "Eduardo", "genero": "M"}).json()["id"]

    resp = client.post(f"/pessoas/{a}/editar", data={
        "nome": "Adelson", "genero": "M", "ativo": "on", "conjuge_id": str(b),
    })
    assert resp.status_code == 200

    # Eduardo nao pode "roubar" a Cassilda de Adelson pela combobox, mas
    # Berenice (solteira) continua disponivel
    form_eduardo = client.get(f"/pessoas/{d}/editar")
    assert "Cassilda" not in form_eduardo.text
    assert "Berenice" in form_eduardo.text

    # a propria tela do Adelson continua oferecendo Cassilda (o conjuge atual dele)
    form_adelson = client.get(f"/pessoas/{a}/editar")
    assert "Cassilda" in form_adelson.text


def test_editar_pessoa_salva_disponibilidade_junto_com_o_cadastro(client):
    # disponibilidade agora fica na propria tela de cadastro do publicador
    # (pessoa), em vez de uma pagina separada com um seletor de pessoa.
    pessoa_id = client.post("/api/pessoas", json={"nome": "Fatima", "genero": "F"}).json()["id"]

    form = client.get(f"/pessoas/{pessoa_id}/editar")
    assert form.status_code == 200
    assert "QUA_CONDOMINIO" in form.text or "Quarta" in form.text

    resp = client.post(f"/pessoas/{pessoa_id}/editar", data={
        "nome": "Fatima", "genero": "F", "ativo": "on",
        "slot_ids": ["SEG_TARDE_ZARGON", "QUA_CONDOMINIO"],
    })
    assert resp.status_code == 200
    disponibilidade = client.get(f"/api/disponibilidades/pessoa/{pessoa_id}").json()
    assert set(disponibilidade) == {"SEG_TARDE_ZARGON", "QUA_CONDOMINIO"}

    # desmarcar um horario na mesma tela remove só aquele
    client.post(f"/pessoas/{pessoa_id}/editar", data={
        "nome": "Fatima", "genero": "F", "ativo": "on",
        "slot_ids": ["QUA_CONDOMINIO"],
    })
    assert client.get(f"/api/disponibilidades/pessoa/{pessoa_id}").json() == ["QUA_CONDOMINIO"]


def test_trocar_conjuge_pela_tela_de_edicao_libera_o_parceiro_antigo(client):
    # bug: pessoas_repo.atualizar() zerava conjuge_id ANTES de
    # cadastro_service.definir_conjuge rodar, entao o servico nunca via quem
    # era o parceiro antigo pra desfazer o vinculo reciproco dele.
    a = client.post("/api/pessoas", json={"nome": "Adelson", "genero": "M"}).json()["id"]
    b = client.post("/api/pessoas", json={"nome": "Cassilda", "genero": "F"}).json()["id"]
    c = client.post("/api/pessoas", json={"nome": "Debora", "genero": "F"}).json()["id"]

    client.post(f"/pessoas/{a}/editar", data={"nome": "Adelson", "genero": "M", "ativo": "on", "conjuge_id": str(b)})
    client.post(f"/pessoas/{a}/editar", data={"nome": "Adelson", "genero": "M", "ativo": "on", "conjuge_id": str(c)})

    pessoas = {p["id"]: p for p in client.get("/api/pessoas").json()}
    assert pessoas[a]["conjuge_id"] == c
    assert pessoas[c]["conjuge_id"] == a
    assert pessoas[b]["conjuge_id"] is None


def test_editar_pessoa_preserva_disponibilidade_de_slot_ja_desativado(client):
    # bug: como a combobox so mostra horarios ATIVOS, qualquer edicao (mesmo
    # sem relacao com disponibilidade) reenviava só os horarios visiveis e
    # apagava em silencio a disponibilidade de um horario ja desativado.
    pessoa_id = client.post("/api/pessoas", json={"nome": "Marta", "genero": "F"}).json()["id"]
    client.post(f"/pessoas/{pessoa_id}/editar", data={
        "nome": "Marta", "genero": "F", "ativo": "on", "slot_ids": ["QUA_CONDOMINIO"],
    })
    assert client.get(f"/api/disponibilidades/pessoa/{pessoa_id}").json() == ["QUA_CONDOMINIO"]

    slot = next(s for s in client.get("/api/slots").json() if s["slot_id"] == "QUA_CONDOMINIO")
    resp = client.post(f"/slots/{slot['slot_id']}/editar", data={
        "dia_semana": slot["dia_semana"], "periodo": slot["periodo"],
        "local": slot["local"], "ordem": str(slot["ordem"]),
        # sem "ativo": desativa o horario
    })
    assert resp.status_code == 200

    # edita um campo sem nenhuma relacao com disponibilidade; a combobox nem
    # mostra mais QUA_CONDOMINIO como opcao
    client.post(f"/pessoas/{pessoa_id}/editar", data={"nome": "Marta Souza", "genero": "F", "ativo": "on"})

    assert client.get(f"/api/disponibilidades/pessoa/{pessoa_id}").json() == ["QUA_CONDOMINIO"]


def test_editar_pessoa_com_slot_inexistente_mostra_erro_em_vez_de_500(client):
    pessoa_id = client.post("/api/pessoas", json={"nome": "Julia", "genero": "F"}).json()["id"]
    resp = client.post(f"/pessoas/{pessoa_id}/editar", data={
        "nome": "Julia", "genero": "F", "ativo": "on", "slot_ids": ["SLOT_FANTASMA"],
    })
    assert resp.status_code == 400
    assert "painel-erro" in resp.text


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
