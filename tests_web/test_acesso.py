"""Login por e-mail, solicitação de acesso e aprovação."""

from tests_web.conftest import codigo_de, criar_congregacao, dar_acesso, entrar

from app.auth import repo
from app.auth.models import Papel, StatusSolicitacao
from app.db import postgres


def test_visitante_anonimo_vai_para_a_tela_de_entrada(cliente):
    for caminho in ["/", "/escala?ano=2026&mes=9", "/pessoas", "/admin"]:
        resposta = cliente.get(caminho)
        assert resposta.status_code == 303, caminho
        assert resposta.headers["location"] == "/entrar", caminho


def test_api_responde_401_em_vez_de_redirecionar(cliente):
    resposta = cliente.get("/api/pessoas")
    assert resposta.status_code == 401
    assert "detail" in resposta.json()


def test_email_sem_conta_e_levado_a_solicitar_acesso(cliente, caixa_de_entrada):
    resposta = cliente.post("/entrar", data={"email": "novato@exemplo.com"})
    assert resposta.status_code == 303
    assert resposta.headers["location"] == "/solicitar-acesso?email=novato@exemplo.com"


def test_super_admin_do_ambiente_entra_sem_ninguem_aprovar(cliente, caixa_de_entrada):
    """O primeiro acesso da instalação: SUPER_ADMIN_EMAIL cria a conta."""
    entrar(cliente, caixa_de_entrada, "chefe@exemplo.com")
    with postgres.get_connection() as conn:
        usuario = repo.obter_usuario_por_email(conn, "chefe@exemplo.com")
        assert usuario is not None and usuario.super_admin


def test_codigo_errado_nao_cria_sessao(cliente, caixa_de_entrada):
    cliente.post("/entrar", data={"email": "chefe@exemplo.com"})
    resposta = cliente.post("/entrar/codigo", data={"email": "chefe@exemplo.com", "codigo": "000001"})
    assert resposta.status_code == 200
    assert not cliente.cookies.get("escala_sessao")


def test_codigo_so_vale_uma_vez(cliente, caixa_de_entrada):
    cliente.post("/entrar", data={"email": "chefe@exemplo.com"})
    codigo = codigo_de(caixa_de_entrada, "chefe@exemplo.com")

    primeira = cliente.post("/entrar/codigo", data={"email": "chefe@exemplo.com", "codigo": codigo})
    assert primeira.status_code == 303

    cliente.cookies.clear()
    segunda = cliente.post("/entrar/codigo", data={"email": "chefe@exemplo.com", "codigo": codigo})
    assert segunda.status_code == 200
    assert not cliente.cookies.get("escala_sessao")


def test_codigo_de_um_email_nao_serve_para_outro(cliente, caixa_de_entrada):
    congregacao = criar_congregacao("Central")
    dar_acesso("outro@exemplo.com", congregacao, Papel.EDITOR)

    cliente.post("/entrar", data={"email": "chefe@exemplo.com"})
    codigo_do_chefe = codigo_de(caixa_de_entrada, "chefe@exemplo.com")

    resposta = cliente.post(
        "/entrar/codigo", data={"email": "outro@exemplo.com", "codigo": codigo_do_chefe}
    )
    assert resposta.status_code == 200
    assert not cliente.cookies.get("escala_sessao")


def test_tentativas_erradas_queimam_o_codigo(cliente, caixa_de_entrada):
    cliente.post("/entrar", data={"email": "chefe@exemplo.com"})
    codigo = codigo_de(caixa_de_entrada, "chefe@exemplo.com")
    errado = "999999" if codigo != "999999" else "111111"

    for _ in range(5):
        cliente.post("/entrar/codigo", data={"email": "chefe@exemplo.com", "codigo": errado})

    # mesmo com o código CERTO, o que sobrou já não vale
    resposta = cliente.post("/entrar/codigo", data={"email": "chefe@exemplo.com", "codigo": codigo})
    assert resposta.status_code == 200
    assert not cliente.cookies.get("escala_sessao")


def test_sair_derruba_a_sessao(cliente, caixa_de_entrada):
    congregacao = criar_congregacao("Central")
    dar_acesso("chefe@exemplo.com", congregacao, Papel.ADMIN)
    entrar(cliente, caixa_de_entrada, "chefe@exemplo.com")

    assert cliente.get("/pessoas").status_code == 200
    cliente.post("/sair")
    assert cliente.get("/pessoas").headers["location"] == "/entrar"


def test_usuario_bloqueado_perde_a_sessao_aberta(cliente, caixa_de_entrada):
    congregacao = criar_congregacao("Central")
    usuario_id = dar_acesso("irmao@exemplo.com", congregacao, Papel.EDITOR)
    entrar(cliente, caixa_de_entrada, "irmao@exemplo.com")
    assert cliente.get("/pessoas").status_code == 200

    with postgres.get_connection() as conn:
        repo.definir_usuario_ativo(conn, usuario_id, False)

    assert cliente.get("/pessoas").headers["location"] == "/entrar"


# === Solicitação e aprovação ===============================================

def test_solicitacao_para_congregacao_existente_e_aprovacao(cliente, caixa_de_entrada):
    congregacao = criar_congregacao("Central")
    dar_acesso("chefe@exemplo.com", congregacao, Papel.ADMIN)

    resposta = cliente.post("/solicitar-acesso", data={
        "email": "novo@exemplo.com", "nome": "Irmão Novo",
        "congregacao": str(congregacao), "mensagem": "cuido do carrinho",
    })
    assert resposta.status_code == 200

    with postgres.get_connection() as conn:
        pendentes = repo.listar_solicitacoes(conn, StatusSolicitacao.PENDENTE)
        assert len(pendentes) == 1
        solicitacao_id = pendentes[0].id

    entrar(cliente, caixa_de_entrada, "chefe@exemplo.com")
    aprovacao = cliente.post(
        f"/admin/solicitacoes/{solicitacao_id}/aprovar", data={"papel": "EDITOR"}
    )
    assert aprovacao.status_code == 303

    with postgres.get_connection() as conn:
        usuario = repo.obter_usuario_por_email(conn, "novo@exemplo.com")
        assert usuario is not None
        assert repo.obter_papel(conn, usuario.id, congregacao) is Papel.EDITOR

    # e agora a pessoa entra de fato
    cliente.cookies.clear()
    entrar(cliente, caixa_de_entrada, "novo@exemplo.com")
    assert cliente.get("/pessoas").status_code == 200


def test_solicitacao_de_congregacao_nova_cria_tudo_e_deixa_admin(cliente, caixa_de_entrada):
    cliente.post("/solicitar-acesso", data={
        "email": "fundador@exemplo.com", "nome": "Fundador",
        "congregacao": "nova", "congregacao_nova": "Jardim das Palmeiras",
    })
    with postgres.get_connection() as conn:
        solicitacao_id = repo.listar_solicitacoes(conn, StatusSolicitacao.PENDENTE)[0].id

    entrar(cliente, caixa_de_entrada, "chefe@exemplo.com")
    assert cliente.post(f"/admin/solicitacoes/{solicitacao_id}/aprovar").status_code == 303

    with postgres.get_connection() as conn:
        congregacao = repo.obter_congregacao_por_slug(conn, "jardim-das-palmeiras")
        assert congregacao is not None
        usuario = repo.obter_usuario_por_email(conn, "fundador@exemplo.com")
        assert repo.obter_papel(conn, usuario.id, congregacao.id) is Papel.ADMIN

    # a congregação nova já nasce com os horários padrão
    cliente.cookies.clear()
    entrar(cliente, caixa_de_entrada, "fundador@exemplo.com")
    pagina = cliente.get("/slots")
    assert pagina.status_code == 200


def test_pedido_repetido_nao_duplica(cliente):
    congregacao = criar_congregacao("Central")
    dados = {"email": "novo@exemplo.com", "nome": "Novo", "congregacao": str(congregacao)}
    cliente.post("/solicitar-acesso", data=dados)
    cliente.post("/solicitar-acesso", data=dados)

    with postgres.get_connection() as conn:
        assert len(repo.listar_solicitacoes(conn, StatusSolicitacao.PENDENTE)) == 1


def test_recusa_nao_da_acesso(cliente, caixa_de_entrada):
    congregacao = criar_congregacao("Central")
    dar_acesso("chefe@exemplo.com", congregacao, Papel.ADMIN)
    cliente.post("/solicitar-acesso", data={
        "email": "recusado@exemplo.com", "nome": "X", "congregacao": str(congregacao)})

    with postgres.get_connection() as conn:
        solicitacao_id = repo.listar_solicitacoes(conn, StatusSolicitacao.PENDENTE)[0].id

    entrar(cliente, caixa_de_entrada, "chefe@exemplo.com")
    assert cliente.post(f"/admin/solicitacoes/{solicitacao_id}/recusar",
                        data={"observacao": "não é da congregação"}).status_code == 303

    with postgres.get_connection() as conn:
        usuario = repo.obter_usuario_por_email(conn, "recusado@exemplo.com")
        assert usuario is None or repo.obter_papel(conn, usuario.id, congregacao) is None


# === Detalhes de segurança ==================================================

def test_troca_de_idioma_nao_redireciona_para_fora(cliente):
    """`destino` vem de um campo do formulário; sem validação, viraria um
    redirecionamento aberto (útil para golpe de phishing com o link do site)."""
    for destino in ["//exemplo-malicioso.com", "https://exemplo-malicioso.com",
                    "/\\exemplo-malicioso.com", "javascript:alert(1)"]:
        resposta = cliente.post("/idioma", data={"idioma": "es", "destino": destino})
        assert resposta.status_code == 303
        assert resposta.headers["location"] == "/entrar", destino

    # um caminho interno de verdade continua funcionando
    resposta = cliente.post("/idioma", data={"idioma": "es", "destino": "/solicitar-acesso"})
    assert resposta.headers["location"] == "/solicitar-acesso"


def test_cookie_de_sessao_e_httponly(cliente, caixa_de_entrada):
    cliente.post("/entrar", data={"email": "chefe@exemplo.com"})
    codigo = codigo_de(caixa_de_entrada, "chefe@exemplo.com")
    resposta = cliente.post("/entrar/codigo", data={"email": "chefe@exemplo.com", "codigo": codigo})

    cabecalho = resposta.headers["set-cookie"]
    assert "escala_sessao=" in cabecalho
    assert "HttpOnly" in cabecalho          # fora do alcance de JavaScript
    assert "SameSite=lax" in cabecalho.replace("Lax", "lax")


def test_token_de_sessao_nao_fica_em_claro_no_banco(cliente, caixa_de_entrada):
    """Uma cópia do banco não pode entregar sessões utilizáveis."""
    entrar(cliente, caixa_de_entrada, "chefe@exemplo.com")
    token = cliente.cookies.get("escala_sessao")

    with postgres.get_connection() as conn:
        guardados = [r["id"] for r in conn.execute("SELECT id FROM sessoes").fetchall()]
    assert guardados and token not in guardados


def test_codigo_nao_fica_em_claro_no_banco(cliente, caixa_de_entrada):
    cliente.post("/entrar", data={"email": "chefe@exemplo.com"})
    codigo = codigo_de(caixa_de_entrada, "chefe@exemplo.com")

    with postgres.get_connection() as conn:
        hashes = [r["codigo_hash"] for r in conn.execute("SELECT codigo_hash FROM codigos_login")]
    assert hashes and codigo not in hashes


def test_avisos_param_de_ser_enviados_sob_enxurrada_mas_pedidos_continuam(
    cliente, caixa_de_entrada
):
    congregacao = criar_congregacao("Central")
    dar_acesso("chefe@exemplo.com", congregacao, Papel.ADMIN)

    for i in range(25):
        cliente.post("/solicitar-acesso", data={
            "email": f"gente{i}@exemplo.com", "nome": f"Pessoa {i}",
            "congregacao": str(congregacao)})

    with postgres.get_connection() as conn:
        pendentes = repo.listar_solicitacoes(conn, StatusSolicitacao.PENDENTE)
    assert len(pendentes) == 25, "todo pedido tem de ser gravado"

    avisos = [m for m in caixa_de_entrada if m["para"] == "chefe@exemplo.com"]
    assert len(avisos) < 25, "o envio de avisos deveria ter sido cortado"
