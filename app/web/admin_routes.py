"""Painel administrativo.

Dois níveis, e a diferença é sempre o ALCANCE, nunca a tela:

  administrador de congregação — vê e decide o que é da(s) congregação(ões)
      em que tem papel ADMIN;
  super-admin — vê tudo, cria e remove congregações, promove outros
      super-admins.

Todo alcance é calculado a partir da sessão já validada. Nenhuma rota aceita
`congregacao_id` da URL como autorização: o id serve para escolher sobre o quê
agir, e logo em seguida é conferido contra o que a sessão permite.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse

from app import config
from app.auth import repo, service
from app.auth.deps import (
    SemPermissao,
    _conexao_do_request,
    congregacoes_que_administra,
    exigir_sessao,
    exigir_super_admin,
    sessao_atual,
)
from app.auth.models import Papel, SessaoAtual, StatusSolicitacao
from app.db.migrations import preparar_congregacao
from app.web.render import render

router = APIRouter(prefix="/admin")


def _exigir_algum_poder(sessao: SessaoAtual) -> None:
    """Barra quem não administra nada — LEITOR/EDITOR não entram no painel."""
    if sessao.usuario.super_admin:
        return
    if not any(m.papel is Papel.ADMIN for m in sessao.membros):
        raise SemPermissao("Só administradores têm acesso ao painel.")


def _conferir_alcance(sessao: SessaoAtual, congregacao_id: int) -> None:
    permitidas = congregacoes_que_administra(sessao)
    if permitidas is not None and congregacao_id not in permitidas:
        raise SemPermissao("Você não administra esta congregação.")


# === Início =================================================================

@router.get("")
def painel(
    request: Request,
    conn=Depends(_conexao_do_request),
    sessao: SessaoAtual = Depends(exigir_sessao),
):
    _exigir_algum_poder(sessao)
    alcance = congregacoes_que_administra(sessao)

    if sessao.usuario.super_admin:
        congregacoes = repo.listar_congregacoes(conn)
        usuarios = repo.listar_usuarios(conn)
    else:
        congregacoes = [c for c in repo.listar_congregacoes(conn) if c.id in (alcance or [])]
        usuarios = []

    return render(
        "admin_painel.html", request, conn,
        pendentes=repo.contar_solicitacoes_pendentes(conn, alcance),
        congregacoes=congregacoes,
        total_usuarios=len(usuarios),
        email_configurado=config.email_configurado(),
        base_url=config.APP_BASE_URL,
    )


# === Solicitações ===========================================================

@router.get("/solicitacoes")
def listar_solicitacoes(
    request: Request,
    status: str = "PENDENTE",
    conn=Depends(_conexao_do_request),
    sessao: SessaoAtual = Depends(exigir_sessao),
):
    _exigir_algum_poder(sessao)
    alcance = congregacoes_que_administra(sessao)

    try:
        filtro = StatusSolicitacao(status)
    except ValueError:
        filtro = StatusSolicitacao.PENDENTE

    solicitacoes = repo.listar_solicitacoes(conn, filtro, alcance)
    return render(
        "admin_solicitacoes.html", request, conn,
        solicitacoes=solicitacoes,
        status_atual=filtro.value,
        papeis=list(Papel),
        pode_criar_congregacao=sessao.usuario.super_admin,
    )


@router.post("/solicitacoes/{solicitacao_id}/aprovar")
async def aprovar(
    solicitacao_id: int,
    request: Request,
    conn=Depends(_conexao_do_request),
    sessao: SessaoAtual = Depends(exigir_sessao),
):
    _exigir_algum_poder(sessao)
    form = await request.form()
    try:
        papel = Papel(str(form.get("papel", Papel.EDITOR.value)))
    except ValueError:
        papel = Papel.EDITOR

    resultado = service.aprovar_solicitacao(
        conn, solicitacao_id, papel, sessao, str(form.get("observacao", ""))
    )
    destino = "/admin/solicitacoes"
    if not resultado.ok:
        destino += f"?erro={resultado.motivo}"
    return RedirectResponse(url=destino, status_code=303)


@router.post("/solicitacoes/{solicitacao_id}/recusar")
async def recusar(
    solicitacao_id: int,
    request: Request,
    conn=Depends(_conexao_do_request),
    sessao: SessaoAtual = Depends(exigir_sessao),
):
    _exigir_algum_poder(sessao)
    form = await request.form()
    resultado = service.recusar_solicitacao(
        conn, solicitacao_id, sessao, str(form.get("observacao", ""))
    )
    destino = "/admin/solicitacoes"
    if not resultado.ok:
        destino += f"?erro={resultado.motivo}"
    return RedirectResponse(url=destino, status_code=303)


# === Pessoas com acesso =====================================================

@router.get("/usuarios")
def listar_usuarios(
    request: Request,
    congregacao_id: int | None = None,
    conn=Depends(_conexao_do_request),
    sessao: SessaoAtual = Depends(exigir_sessao),
):
    _exigir_algum_poder(sessao)
    alcance = congregacoes_que_administra(sessao)

    if congregacao_id is None:
        if sessao.congregacao is not None:
            congregacao_id = sessao.congregacao.id
        elif alcance:
            congregacao_id = alcance[0]
    if congregacao_id is not None:
        _conferir_alcance(sessao, congregacao_id)

    membros = repo.listar_membros_da_congregacao(conn, congregacao_id) if congregacao_id else []
    congregacoes = repo.listar_congregacoes(conn)
    if alcance is not None:
        congregacoes = [c for c in congregacoes if c.id in alcance]

    return render(
        "admin_usuarios.html", request, conn,
        membros=membros,
        congregacoes=congregacoes,
        congregacao_id=congregacao_id,
        papeis=list(Papel),
        super_admin=sessao.usuario.super_admin,
        eu=sessao.usuario,
    )


@router.post("/usuarios/papel")
async def mudar_papel(
    request: Request,
    conn=Depends(_conexao_do_request),
    sessao: SessaoAtual = Depends(exigir_sessao),
):
    _exigir_algum_poder(sessao)
    form = await request.form()
    usuario_id = int(str(form.get("usuario_id")))
    congregacao_id = int(str(form.get("congregacao_id")))
    _conferir_alcance(sessao, congregacao_id)
    papel = Papel(str(form.get("papel")))

    # Rebaixar o último ADMIN deixaria a congregação sem ninguém que possa
    # aprovar acessos ou promover alguém — bloqueio antes de acontecer.
    if papel is not Papel.ADMIN:
        atual = repo.obter_papel(conn, usuario_id, congregacao_id)
        if atual is Papel.ADMIN and repo.contar_admins_da_congregacao(conn, congregacao_id) <= 1:
            return RedirectResponse(
                url=f"/admin/usuarios?congregacao_id={congregacao_id}&erro=ultimo_admin",
                status_code=303,
            )

    repo.definir_membro(conn, usuario_id, congregacao_id, papel)
    return RedirectResponse(url=f"/admin/usuarios?congregacao_id={congregacao_id}", status_code=303)


@router.post("/usuarios/remover")
async def remover_do_grupo(
    request: Request,
    conn=Depends(_conexao_do_request),
    sessao: SessaoAtual = Depends(exigir_sessao),
):
    _exigir_algum_poder(sessao)
    form = await request.form()
    usuario_id = int(str(form.get("usuario_id")))
    congregacao_id = int(str(form.get("congregacao_id")))
    _conferir_alcance(sessao, congregacao_id)

    atual = repo.obter_papel(conn, usuario_id, congregacao_id)
    if atual is Papel.ADMIN and repo.contar_admins_da_congregacao(conn, congregacao_id) <= 1:
        return RedirectResponse(
            url=f"/admin/usuarios?congregacao_id={congregacao_id}&erro=ultimo_admin",
            status_code=303,
        )

    repo.remover_membro(conn, usuario_id, congregacao_id)
    return RedirectResponse(url=f"/admin/usuarios?congregacao_id={congregacao_id}", status_code=303)


@router.post("/usuarios/bloquear")
async def bloquear_usuario(
    request: Request,
    conn=Depends(_conexao_do_request),
    sessao: SessaoAtual = Depends(exigir_super_admin),
):
    form = await request.form()
    usuario_id = int(str(form.get("usuario_id")))
    ativo = str(form.get("ativo", "0")) == "1"

    if usuario_id == sessao.usuario.id and not ativo:
        return RedirectResponse(url="/admin/instalacao?erro=nao_bloqueie_a_si", status_code=303)

    repo.definir_usuario_ativo(conn, usuario_id, ativo)
    return RedirectResponse(url="/admin/instalacao", status_code=303)


# === Instalação (só super-admin) ============================================

@router.get("/instalacao")
def instalacao(
    request: Request,
    conn=Depends(_conexao_do_request),
    sessao: SessaoAtual = Depends(exigir_super_admin),
):
    congregacoes = repo.listar_congregacoes(conn)
    usuarios = repo.listar_usuarios(conn)
    vinculos: dict[int, list[str]] = {}
    for usuario in usuarios:
        vinculos[usuario.id] = [
            f"{m.congregacao_nome} ({m.papel.value.lower()})"
            for m in repo.listar_membros_do_usuario(conn, usuario.id)
        ]

    return render(
        "admin_instalacao.html", request, conn,
        congregacoes=congregacoes,
        usuarios=usuarios,
        vinculos=vinculos,
        eu=sessao.usuario,
        email_configurado=config.email_configurado(),
        base_url=config.APP_BASE_URL,
        super_admins_env=config.SUPER_ADMIN_EMAILS,
    )


@router.post("/congregacoes/criar")
async def criar_congregacao(
    request: Request,
    conn=Depends(_conexao_do_request),
    sessao: SessaoAtual = Depends(exigir_super_admin),
):
    form = await request.form()
    nome = str(form.get("nome", "")).strip()
    if not nome:
        return RedirectResponse(url="/admin/instalacao?erro=nome_vazio", status_code=303)

    congregacao = repo.criar_congregacao(conn, nome, str(form.get("cidade", "")))
    preparar_congregacao(conn, congregacao.id)
    # quem criou entra como ADMIN, senão a congregação nasce sem administrador
    repo.definir_membro(conn, sessao.usuario.id, congregacao.id, Papel.ADMIN)
    return RedirectResponse(url="/admin/instalacao", status_code=303)


@router.post("/congregacoes/{congregacao_id}/renomear")
async def renomear_congregacao(
    congregacao_id: int,
    request: Request,
    conn=Depends(_conexao_do_request),
    sessao: SessaoAtual = Depends(exigir_super_admin),
):
    form = await request.form()
    repo.renomear_congregacao(
        conn, congregacao_id, str(form.get("nome", "")), str(form.get("cidade", ""))
    )
    return RedirectResponse(url="/admin/instalacao", status_code=303)


@router.post("/congregacoes/{congregacao_id}/ativar")
async def ativar_congregacao(
    congregacao_id: int,
    request: Request,
    conn=Depends(_conexao_do_request),
    sessao: SessaoAtual = Depends(exigir_super_admin),
):
    form = await request.form()
    repo.definir_congregacao_ativa(conn, congregacao_id, str(form.get("ativa", "0")) == "1")
    return RedirectResponse(url="/admin/instalacao", status_code=303)


@router.post("/congregacoes/{congregacao_id}/remover")
async def remover_congregacao(
    congregacao_id: int,
    request: Request,
    conn=Depends(_conexao_do_request),
    sessao: SessaoAtual = Depends(exigir_super_admin),
):
    """Apaga a congregação e TODOS os dados dela. Exige digitar o nome exato —
    é irreversível e não há lixeira."""
    form = await request.form()
    congregacao = repo.obter_congregacao(conn, congregacao_id)
    if congregacao is None:
        return RedirectResponse(url="/admin/instalacao", status_code=303)
    if str(form.get("confirmacao", "")).strip() != congregacao.nome:
        return RedirectResponse(url="/admin/instalacao?erro=confirmacao", status_code=303)

    repo.remover_congregacao(conn, congregacao_id)
    return RedirectResponse(url="/admin/instalacao", status_code=303)


@router.post("/usuarios/super-admin")
async def alternar_super_admin(
    request: Request,
    conn=Depends(_conexao_do_request),
    sessao: SessaoAtual = Depends(exigir_super_admin),
):
    form = await request.form()
    usuario_id = int(str(form.get("usuario_id")))
    virar = str(form.get("super_admin", "0")) == "1"

    # Tirar o próprio poder, ou o do último super-admin, tranca a instalação
    # inteira: ninguém mais conseguiria criar congregação nem aprovar acesso.
    if not virar:
        if usuario_id == sessao.usuario.id:
            return RedirectResponse(url="/admin/instalacao?erro=nao_rebaixe_a_si", status_code=303)
        if repo.contar_super_admins(conn) <= 1:
            return RedirectResponse(url="/admin/instalacao?erro=ultimo_super", status_code=303)

    repo.definir_super_admin(conn, usuario_id, virar)
    return RedirectResponse(url="/admin/instalacao", status_code=303)
