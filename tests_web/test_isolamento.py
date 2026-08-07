"""Isolamento entre congregações e limites de cada perfil, pela HTTP.

O smoke de banco (`tests_web/test_banco.py`) prova que o Postgres isola. Aqui
a pergunta é outra: passando pelas rotas reais, com cookie de sessão real,
alguém de uma congregação consegue ver ou mexer no que é de outra?
"""

import pytest
from fastapi.testclient import TestClient

from tests_web.conftest import criar_congregacao, dar_acesso, entrar

from app.auth.models import Papel
from app.db import postgres
from app.main_api import create_app
from app.models import Genero, PessoaIn
from app.repositories import pessoas_repo


def _cadastrar(congregacao_id: int, nomes: list[str]) -> list[int]:
    with postgres.get_connection(congregacao_id) as conn:
        return [
            pessoas_repo.criar(conn, PessoaIn(nome=nome, genero=Genero.M)).id for nome in nomes
        ]


@pytest.fixture
def duas_congregacoes(banco_limpo):
    a = criar_congregacao("Congregação A")
    b = criar_congregacao("Congregação B")
    ids_a = _cadastrar(a, ["Ana da A", "Antonio da A"])
    ids_b = _cadastrar(b, ["Bruno da B", "Beatriz da B"])
    dar_acesso("pessoa.a@exemplo.com", a, Papel.ADMIN)
    dar_acesso("pessoa.b@exemplo.com", b, Papel.ADMIN)
    return {"a": a, "b": b, "ids_a": ids_a, "ids_b": ids_b}


def _cliente_logado(caixa, email: str) -> TestClient:
    cliente = TestClient(create_app(), follow_redirects=False)
    entrar(cliente, caixa, email)
    return cliente


def test_lista_de_pessoas_mostra_so_a_propria_congregacao(duas_congregacoes, caixa_de_entrada):
    cliente_a = _cliente_logado(caixa_de_entrada, "pessoa.a@exemplo.com")
    pagina = cliente_a.get("/pessoas")
    assert pagina.status_code == 200
    assert "Ana da A" in pagina.text
    assert "Bruno da B" not in pagina.text
    assert "Beatriz da B" not in pagina.text


def test_api_de_pessoas_nao_vaza_entre_congregacoes(duas_congregacoes, caixa_de_entrada):
    cliente_b = _cliente_logado(caixa_de_entrada, "pessoa.b@exemplo.com")
    dados = cliente_b.get("/api/pessoas").json()
    nomes = {p["nome"] for p in dados}
    assert nomes == {"Bruno da B", "Beatriz da B"}


def test_id_de_outra_congregacao_nao_e_encontrado(duas_congregacoes, caixa_de_entrada):
    """Adivinhar o id da outra congregação não abre nada: para o Postgres,
    com a congregação da sessão declarada, aquela linha simplesmente não existe."""
    cliente_a = _cliente_logado(caixa_de_entrada, "pessoa.a@exemplo.com")
    id_do_outro = duas_congregacoes["ids_b"][0]

    assert cliente_a.get(f"/api/pessoas/{id_do_outro}").status_code == 404
    assert cliente_a.get(f"/pessoas/{id_do_outro}/editar").status_code == 404


def test_escrita_em_id_de_outra_congregacao_nao_altera_nada(duas_congregacoes, caixa_de_entrada):
    cliente_a = _cliente_logado(caixa_de_entrada, "pessoa.a@exemplo.com")
    id_do_outro = duas_congregacoes["ids_b"][0]

    cliente_a.put(
        f"/api/pessoas/{id_do_outro}",
        json={"nome": "Invadido", "genero": "M", "ativo": True},
    )

    with postgres.get_connection(duas_congregacoes["b"]) as conn:
        nomes = {p.nome for p in pessoas_repo.listar(conn)}
    assert "Invadido" not in nomes
    assert "Bruno da B" in nomes


def test_cada_congregacao_tem_a_propria_escala(duas_congregacoes, caixa_de_entrada):
    cliente_a = _cliente_logado(caixa_de_entrada, "pessoa.a@exemplo.com")
    assert cliente_a.post("/escala/gerar", data={"ano": "2026", "mes": "9"}).status_code == 303

    cliente_b = _cliente_logado(caixa_de_entrada, "pessoa.b@exemplo.com")
    escala_b = cliente_b.get("/escala?ano=2026&mes=9")
    assert escala_b.status_code == 200
    assert "Ana da A" not in escala_b.text
    assert "Antonio da A" not in escala_b.text


# === Perfis =================================================================

def test_leitor_ve_mas_nao_altera(banco_limpo, caixa_de_entrada):
    congregacao = criar_congregacao("Central")
    _cadastrar(congregacao, ["Alguém"])
    dar_acesso("leitor@exemplo.com", congregacao, Papel.LEITOR)

    cliente = _cliente_logado(caixa_de_entrada, "leitor@exemplo.com")
    assert cliente.get("/pessoas").status_code == 200

    resposta = cliente.post("/pessoas", data={"nome": "Intruso", "genero": "M"})
    assert resposta.status_code == 403

    with postgres.get_connection(congregacao) as conn:
        assert "Intruso" not in {p.nome for p in pessoas_repo.listar(conn)}


def test_editor_altera_mas_nao_entra_no_painel(banco_limpo, caixa_de_entrada):
    congregacao = criar_congregacao("Central")
    dar_acesso("editor@exemplo.com", congregacao, Papel.EDITOR)

    cliente = _cliente_logado(caixa_de_entrada, "editor@exemplo.com")
    assert cliente.post("/pessoas", data={"nome": "Novo Irmão", "genero": "M"}).status_code == 303
    assert cliente.get("/admin").status_code == 403


def test_admin_de_uma_congregacao_nao_administra_a_outra(duas_congregacoes, caixa_de_entrada):
    cliente_a = _cliente_logado(caixa_de_entrada, "pessoa.a@exemplo.com")

    painel = cliente_a.get("/admin/usuarios?congregacao_id=" + str(duas_congregacoes["b"]))
    assert painel.status_code == 403

    # e também não consegue mexer nos perfis de lá
    resposta = cliente_a.post("/admin/usuarios/papel", data={
        "usuario_id": "1", "congregacao_id": str(duas_congregacoes["b"]), "papel": "ADMIN"})
    assert resposta.status_code == 403


def test_admin_de_congregacao_nao_abre_a_tela_da_instalacao(duas_congregacoes, caixa_de_entrada):
    cliente_a = _cliente_logado(caixa_de_entrada, "pessoa.a@exemplo.com")
    assert cliente_a.get("/admin/instalacao").status_code == 403
    assert cliente_a.post("/admin/congregacoes/criar", data={"nome": "Minha"}).status_code == 403


def test_admin_so_ve_solicitacoes_da_propria_congregacao(duas_congregacoes, caixa_de_entrada):
    cliente = TestClient(create_app(), follow_redirects=False)
    cliente.post("/solicitar-acesso", data={
        "email": "quer.a@exemplo.com", "nome": "Quer A",
        "congregacao": str(duas_congregacoes["a"])})
    cliente.post("/solicitar-acesso", data={
        "email": "quer.b@exemplo.com", "nome": "Quer B",
        "congregacao": str(duas_congregacoes["b"])})

    cliente_a = _cliente_logado(caixa_de_entrada, "pessoa.a@exemplo.com")
    pagina = cliente_a.get("/admin/solicitacoes")
    assert pagina.status_code == 200
    assert "quer.a@exemplo.com" in pagina.text
    assert "quer.b@exemplo.com" not in pagina.text


def test_admin_nao_aprova_solicitacao_de_outra_congregacao(duas_congregacoes, caixa_de_entrada):
    from app.auth import repo
    from app.auth.models import StatusSolicitacao

    cliente = TestClient(create_app(), follow_redirects=False)
    cliente.post("/solicitar-acesso", data={
        "email": "quer.b@exemplo.com", "nome": "Quer B",
        "congregacao": str(duas_congregacoes["b"])})

    with postgres.get_connection() as conn:
        solicitacao_id = repo.listar_solicitacoes(conn, StatusSolicitacao.PENDENTE)[0].id

    cliente_a = _cliente_logado(caixa_de_entrada, "pessoa.a@exemplo.com")
    cliente_a.post(f"/admin/solicitacoes/{solicitacao_id}/aprovar", data={"papel": "ADMIN"})

    with postgres.get_connection() as conn:
        usuario = repo.obter_usuario_por_email(conn, "quer.b@exemplo.com")
        assert usuario is None or repo.obter_papel(conn, usuario.id, duas_congregacoes["b"]) is None


def test_pessoa_em_duas_congregacoes_troca_e_ve_o_conjunto_certo(
    duas_congregacoes, caixa_de_entrada
):
    dar_acesso("dupla@exemplo.com", duas_congregacoes["a"], Papel.ADMIN)
    dar_acesso("dupla@exemplo.com", duas_congregacoes["b"], Papel.LEITOR)

    cliente = _cliente_logado(caixa_de_entrada, "dupla@exemplo.com")
    primeira = cliente.get("/pessoas")
    assert "Ana da A" in primeira.text and "Bruno da B" not in primeira.text

    assert cliente.post("/trocar-congregacao",
                        data={"congregacao_id": str(duas_congregacoes["b"])}).status_code == 303
    segunda = cliente.get("/pessoas")
    assert "Bruno da B" in segunda.text and "Ana da A" not in segunda.text

    # em B o perfil é de leitura: escrever tem de ser recusado
    assert cliente.post("/pessoas", data={"nome": "X", "genero": "M"}).status_code == 403


def test_nao_da_para_trocar_para_congregacao_alheia(duas_congregacoes, caixa_de_entrada):
    cliente_a = _cliente_logado(caixa_de_entrada, "pessoa.a@exemplo.com")
    cliente_a.post("/trocar-congregacao", data={"congregacao_id": str(duas_congregacoes["b"])})

    pagina = cliente_a.get("/pessoas")
    assert "Ana da A" in pagina.text
    assert "Bruno da B" not in pagina.text


def test_pdf_sai_por_congregacao_e_nao_deixa_rastro(duas_congregacoes, caixa_de_entrada):
    """No modo hospedado o PDF é gravado em disco temporário com nome único e
    apagado depois do envio: com nome fixo, dois pedidos simultâneos do mesmo
    mês na mesma instância serverless entregariam o PDF um do outro."""
    import os

    from app import config

    cliente_a = _cliente_logado(caixa_de_entrada, "pessoa.a@exemplo.com")
    cliente_a.post("/escala/gerar", data={"ano": "2026", "mes": "9"})

    antes = set(os.listdir(config.ESCALAS_DIR)) if config.ESCALAS_DIR.exists() else set()

    resposta = cliente_a.get("/escala/pdf?ano=2026&mes=9")
    assert resposta.status_code == 200
    assert resposta.headers["content-type"] == "application/pdf"
    assert len(resposta.content) > 500
    # o nome oferecido ao usuário não carrega o sufixo aleatório do disco
    assert "CARRINHO_2026-09.pdf" in resposta.headers["content-disposition"]

    depois = set(os.listdir(config.ESCALAS_DIR))
    assert depois == antes, f"sobrou arquivo temporário: {depois - antes}"
