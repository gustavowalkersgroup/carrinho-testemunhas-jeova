"""Renderização compartilhada entre as telas de domínio e as de acesso.

As telas de entrada e de solicitação de acesso são anônimas: não há congregação
selecionada, então o idioma não pode vir da tabela de configurações. Vem de um
cookie (escolhido na própria tela de entrada) e, na falta dele, do padrão.
"""

from __future__ import annotations

from typing import Optional

from fastapi import Request
from fastapi.templating import Jinja2Templates

from app import config, i18n
from app.repositories import configuracoes_repo
from app.services import demo_service

templates = Jinja2Templates(directory=str(config.TEMPLATES_DIR))

COOKIE_IDIOMA = "escala_idioma"


def idioma_do_request(request: Request, conn=None) -> str:
    """Congregação ativa manda; depois o cookie; depois o padrão."""
    if conn is not None:
        sessao = getattr(request.state, "sessao", None)
        tem_congregacao = config.MODO_LOCAL or (sessao is not None and sessao.congregacao)
        if tem_congregacao:
            idioma = configuracoes_repo.obter(conn, "idioma", "")
            if idioma in i18n.IDIOMAS:
                return idioma

    do_cookie = request.cookies.get(COOKIE_IDIOMA, "")
    if do_cookie in i18n.IDIOMAS:
        return do_cookie
    return i18n.IDIOMA_PADRAO


def render(
    nome_template: str,
    request: Request,
    conn=None,
    status_code: int = 200,
    idioma: Optional[str] = None,
    **contexto,
):
    idioma = idioma or contexto.pop("idioma", None) or idioma_do_request(request, conn)
    sessao = getattr(request.state, "sessao", None)

    contexto["request"] = request
    contexto["t"] = lambda chave, **kw: i18n.t(idioma, chave, **kw)
    contexto["t_aviso"] = lambda a: i18n.render_aviso(idioma, a)
    contexto["idioma_atual"] = idioma
    contexto["rtl"] = idioma in i18n.IDIOMAS_RTL
    contexto["idiomas_disponiveis"] = i18n.IDIOMAS
    contexto["sessao"] = sessao
    contexto["modo_web"] = config.MODO_WEB
    contexto["em_modo_demo"] = bool(
        sessao and sessao.congregacao and sessao.congregacao.slug == demo_service.SLUG_CONGREGACAO_DEMO
    )

    if "nome_congregacao" not in contexto:
        nome = ""
        if conn is not None and (config.MODO_LOCAL or (sessao and sessao.congregacao)):
            nome = configuracoes_repo.obter(conn, "nome_congregacao", "") or ""
        if not nome and sessao and sessao.congregacao:
            nome = sessao.congregacao.nome
        contexto["nome_congregacao"] = nome

    return templates.TemplateResponse(nome_template, contexto, status_code=status_code)
