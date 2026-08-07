"""Dependências do FastAPI que ligam sessão, congregação e conexão.

Uma conexão por request, e não uma por dependência: `_conexao_do_request` é
cacheada pelo FastAPI dentro do request, então a sessão é lida e as rotas
trabalham na MESMA transação. Em serverless isso importa — cada conexão nova
custa uma ida e volta ao banco.

A ordem também importa: `sessao_atual` roda antes de `get_conn` e é quem chama
`definir_congregacao`. Quando a rota recebe a conexão, o Postgres já sabe em
qual congregação ela pode mexer.
"""

from __future__ import annotations

from typing import Optional

from fastapi import Depends, Request

from app import config
from app.auth import service
from app.auth.models import Congregacao, Papel, SessaoAtual, Usuario
from app.db.connection import get_connection


class PrecisaEntrar(Exception):
    """Ninguém autenticado. O handler manda para a tela de entrada."""


class PrecisaEscolherCongregacao(Exception):
    """Autenticado, mas ainda sem congregação ativa (nenhum vínculo aprovado)."""


class SemPermissao(Exception):
    def __init__(self, detalhe: str = "Você não tem permissão para esta ação."):
        super().__init__(detalhe)
        self.detalhe = detalhe


# Sessão sintética do modo desktop: um computador, uma congregação, sem login.
_SESSAO_LOCAL = SessaoAtual(
    usuario=Usuario(id=0, email="local", nome="Uso local", super_admin=True),
    congregacao=Congregacao(id=config.CONGREGACAO_LOCAL_ID, nome="", slug="local"),
    papel=Papel.ADMIN,
)


def _conexao_do_request(request: Request):
    """Abre a conexão do request. Cacheada pelo FastAPI: chamada uma vez só."""
    with get_connection() as conn:
        request.state.conn = conn
        yield conn


def sessao_atual(request: Request, conn=Depends(_conexao_do_request)) -> Optional[SessaoAtual]:
    """Quem está acessando — ou None. Não exige login: rotas públicas (entrar,
    solicitar acesso) também passam por aqui para montar o cabeçalho."""
    if config.MODO_LOCAL:
        request.state.sessao = _SESSAO_LOCAL
        return _SESSAO_LOCAL

    token = request.cookies.get(config.SESSAO_COOKIE)
    sessao = service.carregar_sessao(conn, token)
    request.state.sessao = sessao

    # o resto do request (inclusive as rotas de domínio) enxerga só esta
    # congregação; sem sessão, o Postgres não devolve linha nenhuma.
    conn.definir_congregacao(sessao.congregacao.id if sessao and sessao.congregacao else None)
    return sessao


def exigir_sessao(sessao: Optional[SessaoAtual] = Depends(sessao_atual)) -> SessaoAtual:
    if sessao is None:
        raise PrecisaEntrar()
    return sessao


def exigir_congregacao(sessao: SessaoAtual = Depends(exigir_sessao)) -> SessaoAtual:
    if sessao.congregacao is None:
        raise PrecisaEscolherCongregacao()
    return sessao


def exigir_edicao(sessao: SessaoAtual = Depends(exigir_congregacao)) -> SessaoAtual:
    if not sessao.pode_editar:
        raise SemPermissao("Seu perfil nesta congregação permite apenas consultar a escala.")
    return sessao


def exigir_admin_da_congregacao(sessao: SessaoAtual = Depends(exigir_congregacao)) -> SessaoAtual:
    if not sessao.pode_administrar_congregacao:
        raise SemPermissao("Só um administrador da congregação pode fazer isso.")
    return sessao


_METODOS_QUE_ESCREVEM = {"POST", "PUT", "PATCH", "DELETE"}


def exigir_acesso(request: Request, sessao: SessaoAtual = Depends(exigir_congregacao)) -> SessaoAtual:
    """Guarda aplicada a TODAS as rotas de domínio de uma vez (no include_router).

    Ler exige pertencer à congregação; escrever exige perfil de edição. Fazer
    isso pelo método HTTP, e não rota a rota, garante que uma rota nova nasça
    protegida em vez de depender de alguém lembrar de anotá-la."""
    if request.method in _METODOS_QUE_ESCREVEM and not sessao.pode_editar:
        raise SemPermissao("Seu perfil nesta congregação permite apenas consultar a escala.")
    return sessao


def exigir_super_admin(sessao: SessaoAtual = Depends(exigir_sessao)) -> SessaoAtual:
    if not sessao.usuario.super_admin:
        raise SemPermissao("Só o administrador da instalação pode fazer isso.")
    return sessao


def get_conn(conn=Depends(_conexao_do_request), _s=Depends(sessao_atual)):
    """Conexão já apontada para a congregação da sessão.

    Depende de `sessao_atual` de propósito: garante que `definir_congregacao`
    já rodou. Sem isso a rota trabalharia numa conexão sem congregação e as
    consultas voltariam vazias."""
    return conn


def congregacoes_que_administra(sessao: SessaoAtual) -> Optional[list[int]]:
    """Ids que a pessoa pode administrar. None = todas (super-admin)."""
    if sessao.usuario.super_admin:
        return None
    return [m.congregacao_id for m in sessao.membros if m.papel is Papel.ADMIN]
