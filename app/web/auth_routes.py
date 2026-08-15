"""Telas públicas de acesso: entrar, confirmar código, solicitar acesso, sair.

São as únicas rotas do modo WEB que não exigem sessão — por isso ficam num
router separado, sem a dependência `exigir_acesso` que protege o resto.
"""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse

from app import config, i18n
from app.auth import repo, service
from app.auth.deps import _conexao_do_request, exigir_sessao, sessao_atual
from app.auth.models import SessaoAtual
from app.auth.service import ResultadoLogin, ResultadoPedido, ResultadoSolicitacao
from app.services import demo_service
from app.web.render import COOKIE_IDIOMA, render

router = APIRouter()


def _texto(request, conn, chave: str) -> str:
    from app.web.render import idioma_do_request

    return i18n.t(idioma_do_request(request, conn), chave)


def _definir_cookie_sessao(resposta: RedirectResponse, token: str) -> RedirectResponse:
    resposta.set_cookie(
        config.SESSAO_COOKIE,
        token,
        max_age=config.SESSAO_DURACAO_DIAS * 24 * 3600,
        httponly=True,          # fora do alcance de JavaScript
        secure=config.COOKIE_SEGURO,
        samesite="lax",         # não vai junto em request cross-site (anti-CSRF)
        path="/",
    )
    return resposta


# === Entrar =================================================================

@router.get("/entrar")
def pagina_entrar(
    request: Request,
    email: str = "",
    aviso: str = "",
    conn=Depends(_conexao_do_request),
    sessao=Depends(sessao_atual),
):
    if sessao is not None:
        return RedirectResponse(url="/", status_code=303)
    return render("entrar.html", request, conn, email=email, aviso=aviso, etapa="email")


# === Demonstração ============================================================
# Acesso sem login a uma congregação fictícia (40 pessoas, 10 casais), pra
# mostrar o sistema funcionando sem precisar de código por e-mail. Reseta
# periodicamente (ver app/services/demo_service.py e
# POST /api/automacao/resetar-demo).

@router.get("/demo")
def entrar_demo(
    request: Request,
    conn=Depends(_conexao_do_request),
    sessao=Depends(sessao_atual),
):
    if not config.MODO_WEB:
        return RedirectResponse(url="/", status_code=303)
    if sessao is not None:
        # já logado (numa conta de verdade ou já na própria demo) -- não troca
        # a sessão por baixo dos panos.
        return RedirectResponse(url="/", status_code=303)

    congregacao = demo_service.garantir_demo_congregacao(conn)
    usuario = repo.obter_usuario_por_email(conn, demo_service.EMAIL_USUARIO_DEMO)

    token = secrets.token_urlsafe(32)
    repo.criar_sessao(
        conn, service.hash_token_sessao(token), usuario.id, congregacao.id,
        config.SESSAO_DURACAO_DIAS, request.headers.get("user-agent", ""),
    )

    resposta = RedirectResponse(url="/", status_code=303)
    return _definir_cookie_sessao(resposta, token)


@router.post("/demo/reiniciar")
def reiniciar_demo(sessao=Depends(exigir_sessao)):
    """Botão manual dentro da própria demo. Reseta AGORA em vez de esperar o
    cron diário -- útil antes de mostrar o sistema pra alguém."""
    if not sessao.congregacao or sessao.congregacao.slug != demo_service.SLUG_CONGREGACAO_DEMO:
        return RedirectResponse(url="/", status_code=303)
    demo_service.resetar_demo()
    return RedirectResponse(url="/demo", status_code=303)


@router.post("/entrar")
async def solicitar_codigo(
    request: Request, conn=Depends(_conexao_do_request), sessao=Depends(sessao_atual)
):
    form = await request.form()
    email = repo.normalizar_email(str(form.get("email", "")))
    if not email:
        return render("entrar.html", request, conn, etapa="email",
                      erro=_texto(request, conn, "acesso.erro_email_vazio"))

    pedido = service.pedir_codigo(conn, email, request.headers.get("user-agent", ""))

    if pedido.resultado is ResultadoPedido.SEM_CONTA:
        # Em vez de um "e-mail não encontrado" sem saída, leva direto ao
        # formulário de solicitação já preenchido: é o caminho que a pessoa
        # precisa seguir de qualquer forma.
        return RedirectResponse(url=f"/solicitar-acesso?email={email}", status_code=303)

    if pedido.resultado is not ResultadoPedido.ENVIADO:
        chaves = {
            ResultadoPedido.BLOQUEADO: "acesso.erro_bloqueado",
            ResultadoPedido.EXCESSO_DE_PEDIDOS: "acesso.erro_excesso",
            ResultadoPedido.SEM_PROVEDOR: "acesso.erro_sem_provedor",
            ResultadoPedido.FALHA_NO_ENVIO: "acesso.erro_envio",
        }
        return render("entrar.html", request, conn, etapa="email", email=email,
                      erro=_texto(request, conn, chaves[pedido.resultado]))

    return render(
        "entrar.html", request, conn, etapa="codigo", email=email,
        # só vem preenchido na instalação ainda sem provedor de e-mail, e só
        # para super-admin (ver auth/service.pedir_codigo)
        codigo_visivel=pedido.codigo_visivel,
    )


@router.post("/entrar/codigo")
async def confirmar_codigo(
    request: Request, conn=Depends(_conexao_do_request), sessao=Depends(sessao_atual)
):
    form = await request.form()
    email = repo.normalizar_email(str(form.get("email", "")))
    codigo = str(form.get("codigo", ""))

    login = service.confirmar_codigo(conn, email, codigo, request.headers.get("user-agent", ""))
    if login.resultado is not ResultadoLogin.OK:
        chaves = {
            ResultadoLogin.CODIGO_INVALIDO: "acesso.erro_codigo_invalido",
            ResultadoLogin.CODIGO_EXPIRADO: "acesso.erro_codigo_expirado",
            ResultadoLogin.TENTATIVAS_ESGOTADAS: "acesso.erro_tentativas",
            ResultadoLogin.BLOQUEADO: "acesso.erro_bloqueado",
        }
        return render("entrar.html", request, conn, etapa="codigo", email=email,
                      erro=_texto(request, conn, chaves[login.resultado]))

    resposta = RedirectResponse(url="/", status_code=303)
    return _definir_cookie_sessao(resposta, login.token)


@router.post("/sair")
def sair(request: Request, conn=Depends(_conexao_do_request), sessao=Depends(sessao_atual)):
    service.encerrar_sessao(conn, request.cookies.get(config.SESSAO_COOKIE))
    resposta = RedirectResponse(url="/entrar", status_code=303)
    resposta.delete_cookie(config.SESSAO_COOKIE, path="/")
    return resposta


@router.post("/trocar-congregacao")
async def trocar_congregacao(
    request: Request,
    conn=Depends(_conexao_do_request),
    sessao: SessaoAtual = Depends(exigir_sessao),
):
    form = await request.form()
    try:
        congregacao_id = int(str(form.get("congregacao_id", "")))
    except ValueError:
        return RedirectResponse(url="/", status_code=303)

    service.trocar_congregacao(
        conn, request.cookies.get(config.SESSAO_COOKIE, ""), congregacao_id, sessao
    )
    return RedirectResponse(url="/", status_code=303)


@router.post("/idioma")
async def trocar_idioma_publico(request: Request):
    """Troca de idioma nas telas anônimas (grava em cookie). Dentro de uma
    congregação o idioma vem das configurações dela, não daqui."""
    form = await request.form()
    idioma = str(form.get("idioma", ""))
    destino = str(form.get("destino", "/entrar")) or "/entrar"
    # Só caminho interno. "/" sozinho não basta como teste: "//exemplo.com" e
    # "/\exemplo.com" também começam com barra e o navegador os trata como
    # endereço externo — seria um redirecionamento aberto.
    if not destino.startswith("/") or destino[:2] in ("//", "/\\") or ":" in destino:
        destino = "/entrar"
    resposta = RedirectResponse(url=destino, status_code=303)
    if idioma in i18n.IDIOMAS:
        resposta.set_cookie(COOKIE_IDIOMA, idioma, max_age=365 * 24 * 3600,
                            samesite="lax", secure=config.COOKIE_SEGURO, path="/")
    return resposta


# === Solicitar acesso =======================================================

@router.get("/solicitar-acesso")
def pagina_solicitar(
    request: Request,
    email: str = "",
    conn=Depends(_conexao_do_request),
    sessao=Depends(sessao_atual),
):
    return render(
        "solicitar_acesso.html", request, conn,
        email=repo.normalizar_email(email),
        congregacoes=repo.listar_congregacoes(conn, somente_ativas=True),
    )


@router.post("/solicitar-acesso")
async def enviar_solicitacao(
    request: Request, conn=Depends(_conexao_do_request), sessao=Depends(sessao_atual)
):
    form = await request.form()
    email = repo.normalizar_email(str(form.get("email", "")))
    nome = str(form.get("nome", ""))
    mensagem = str(form.get("mensagem", ""))
    escolha = str(form.get("congregacao", ""))

    congregacao_id, congregacao_nova = None, ""
    if escolha == "nova":
        congregacao_nova = str(form.get("congregacao_nova", ""))
    elif escolha:
        try:
            congregacao_id = int(escolha)
        except ValueError:
            congregacao_id = None

    pedido = service.solicitar_acesso(conn, email, nome, congregacao_id, congregacao_nova, mensagem)

    if pedido.resultado is ResultadoSolicitacao.DADOS_INVALIDOS:
        return render("solicitar_acesso.html", request, conn, email=email, nome=nome,
                      congregacoes=repo.listar_congregacoes(conn, somente_ativas=True),
                      erro=_texto(request, conn, "acesso.erro_solicitacao_invalida"))

    if pedido.resultado is ResultadoSolicitacao.JA_TEM_ACESSO:
        return RedirectResponse(url=f"/entrar?email={email}", status_code=303)

    return render("solicitacao_enviada.html", request, conn, email=email,
                  ja_pendente=pedido.resultado is ResultadoSolicitacao.JA_PENDENTE)
