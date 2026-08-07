"""Regras de autenticação e de aprovação de acesso.

Login sem senha: a pessoa informa o e-mail, recebe um código de 6 dígitos e o
digita de volta. Não há senha para vazar, esquecer ou reaproveitar, e o e-mail
já é a identidade que o administrador usa para aprovar quem entra.

O que é guardado no banco é sempre o HASH — do código e do token de sessão —
para que uma cópia do banco não sirva para entrar como ninguém.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from app import config
from app.auth import email_envio, repo
from app.auth.models import (
    Congregacao,
    Papel,
    SessaoAtual,
    Solicitacao,
    StatusSolicitacao,
    Usuario,
)

logger = logging.getLogger("escala.auth")

# Sem SECRET_KEY definida, um segredo efêmero por processo. Serve para
# desenvolvimento; em produção serverless cada instância teria o seu, e as
# sessões cairiam a cada troca de instância — por isso main_api avisa.
_SEGREDO = config.SECRET_KEY or secrets.token_hex(32)


def _hash_codigo(email: str, codigo: str) -> str:
    return hmac.new(
        _SEGREDO.encode(), f"{repo.normalizar_email(email)}:{codigo}".encode(), hashlib.sha256
    ).hexdigest()


def hash_token_sessao(token: str) -> str:
    # O token tem 256 bits de entropia; não precisa de KDF lento, só de não
    # ficar em claro no banco.
    return hashlib.sha256(token.encode()).hexdigest()


# === Bootstrap ==============================================================

def garantir_super_admins(conn) -> None:
    """Promove a super-admin todo e-mail listado em SUPER_ADMIN_EMAIL.

    É o único jeito de uma instalação nova ganhar seu primeiro administrador:
    sem isso não haveria quem aprovasse a primeira solicitação."""
    for email in config.SUPER_ADMIN_EMAILS:
        usuario = repo.obter_usuario_por_email(conn, email)
        if usuario is None:
            repo.criar_usuario(conn, email, nome="", super_admin=True)
            logger.info("super-admin criado a partir de SUPER_ADMIN_EMAIL: %s", email)
        elif not usuario.super_admin:
            repo.definir_super_admin(conn, usuario.id, True)


# === Pedido de código =======================================================

class ResultadoPedido(str, Enum):
    ENVIADO = "ENVIADO"
    # e-mail sem conta: a pessoa precisa solicitar acesso primeiro
    SEM_CONTA = "SEM_CONTA"
    # conta existe mas foi desativada por um administrador
    BLOQUEADO = "BLOQUEADO"
    # pediu códigos demais na última hora
    EXCESSO_DE_PEDIDOS = "EXCESSO_DE_PEDIDOS"
    # não há provedor de e-mail e este endereço não é super-admin
    SEM_PROVEDOR = "SEM_PROVEDOR"
    FALHA_NO_ENVIO = "FALHA_NO_ENVIO"


@dataclass
class Pedido:
    resultado: ResultadoPedido
    # preenchido só quando o código foi "enviado" via log (instalação ainda
    # sem provedor de e-mail, endereço de super-admin) — a rota mostra na tela
    # para destravar o primeiro acesso.
    codigo_visivel: Optional[str] = None
    detalhe: str = ""


def pedir_codigo(conn, email: str, user_agent: str = "") -> Pedido:
    email = repo.normalizar_email(email)
    garantir_super_admins(conn)

    usuario = repo.obter_usuario_por_email(conn, email)
    if usuario is None:
        return Pedido(ResultadoPedido.SEM_CONTA)
    if not usuario.ativo:
        return Pedido(ResultadoPedido.BLOQUEADO)

    if repo.codigos_pedidos_na_ultima_hora(conn, email) >= config.CODIGO_LOGIN_MAX_POR_HORA:
        return Pedido(ResultadoPedido.EXCESSO_DE_PEDIDOS)

    e_super_admin = usuario.super_admin or email in config.SUPER_ADMIN_EMAILS
    if not config.email_configurado() and not e_super_admin:
        # Mostrar o código na tela para qualquer um seria entregar a conta a
        # quem digitasse o e-mail alheio. Só o super-admin passa por aqui, e
        # só para conseguir configurar o provedor de e-mail.
        return Pedido(ResultadoPedido.SEM_PROVEDOR)

    codigo = f"{secrets.randbelow(1_000_000):06d}"
    # um código novo invalida os anteriores: senão vários códigos ficariam
    # valendo ao mesmo tempo e o limite de tentativas perderia o sentido.
    repo.invalidar_codigos(conn, email)
    repo.criar_codigo(conn, email, _hash_codigo(email, codigo),
                      config.CODIGO_LOGIN_VALIDADE_MINUTOS)

    try:
        via = email_envio.enviar_codigo_login(email, codigo)
    except email_envio.FalhaNoEnvio as e:
        logger.error("falha ao enviar código para %s: %s", email, e)
        return Pedido(ResultadoPedido.FALHA_NO_ENVIO, detalhe=str(e))

    if via == "log":
        return Pedido(ResultadoPedido.ENVIADO, codigo_visivel=codigo)
    return Pedido(ResultadoPedido.ENVIADO)


# === Confirmação do código ==================================================

class ResultadoLogin(str, Enum):
    OK = "OK"
    CODIGO_INVALIDO = "CODIGO_INVALIDO"
    CODIGO_EXPIRADO = "CODIGO_EXPIRADO"
    TENTATIVAS_ESGOTADAS = "TENTATIVAS_ESGOTADAS"
    BLOQUEADO = "BLOQUEADO"


@dataclass
class Login:
    resultado: ResultadoLogin
    token: Optional[str] = None
    usuario: Optional[Usuario] = None


def confirmar_codigo(conn, email: str, codigo: str, user_agent: str = "") -> Login:
    email = repo.normalizar_email(email)
    codigo = (codigo or "").strip().replace(" ", "").replace("-", "")

    usuario = repo.obter_usuario_por_email(conn, email)
    if usuario is None or not usuario.ativo:
        return Login(ResultadoLogin.BLOQUEADO)

    linha = repo.obter_codigo_valido(conn, email)
    if linha is None:
        return Login(ResultadoLogin.CODIGO_EXPIRADO)
    if linha["tentativas"] >= config.CODIGO_LOGIN_MAX_TENTATIVAS:
        repo.marcar_codigo_usado(conn, linha["id"])
        return Login(ResultadoLogin.TENTATIVAS_ESGOTADAS)

    if not hmac.compare_digest(linha["codigo_hash"], _hash_codigo(email, codigo)):
        repo.registrar_tentativa_errada(conn, linha["id"])
        restantes = config.CODIGO_LOGIN_MAX_TENTATIVAS - (linha["tentativas"] + 1)
        if restantes <= 0:
            repo.marcar_codigo_usado(conn, linha["id"])
            return Login(ResultadoLogin.TENTATIVAS_ESGOTADAS)
        return Login(ResultadoLogin.CODIGO_INVALIDO)

    repo.marcar_codigo_usado(conn, linha["id"])
    repo.registrar_acesso(conn, usuario.id)

    # a congregação inicial da sessão é a primeira do usuário; quem participa
    # de várias troca depois pelo seletor.
    membros = repo.listar_membros_do_usuario(conn, usuario.id)
    congregacao_id = membros[0].congregacao_id if membros else None

    token = secrets.token_urlsafe(32)
    repo.criar_sessao(conn, hash_token_sessao(token), usuario.id, congregacao_id,
                      config.SESSAO_DURACAO_DIAS, user_agent)

    # boa hora para varrer o lixo: barato e sem necessidade de agendador.
    repo.limpar_sessoes_expiradas(conn)
    repo.limpar_codigos_expirados(conn)

    return Login(ResultadoLogin.OK, token=token, usuario=usuario)


# === Sessão ativa ===========================================================

def carregar_sessao(conn, token: Optional[str]) -> Optional[SessaoAtual]:
    if not token:
        return None
    linha = repo.obter_sessao(conn, hash_token_sessao(token))
    if linha is None:
        return None

    usuario = repo.obter_usuario(conn, linha["usuario_id"])
    if usuario is None or not usuario.ativo:
        return None

    membros = repo.listar_membros_do_usuario(conn, usuario.id)
    congregacao: Optional[Congregacao] = None
    papel: Optional[Papel] = None

    congregacao_id = linha["congregacao_id"]
    if congregacao_id is None and membros:
        # entrou antes de pertencer a alguma congregação (ou perdeu o vínculo
        # que estava selecionado): assume a primeira disponível.
        congregacao_id = membros[0].congregacao_id
        repo.trocar_congregacao_da_sessao(conn, linha["id"], congregacao_id)

    if congregacao_id is not None:
        congregacao = repo.obter_congregacao(conn, congregacao_id)
        papel = repo.obter_papel(conn, usuario.id, congregacao_id)
        if congregacao is None or (papel is None and not usuario.super_admin):
            congregacao, papel = None, None

    return SessaoAtual(usuario=usuario, congregacao=congregacao, papel=papel, membros=membros)


def trocar_congregacao(conn, token: str, congregacao_id: int, sessao: SessaoAtual) -> bool:
    """Só permite trocar para congregação em que a pessoa realmente entra."""
    permitidas = {m.congregacao_id for m in sessao.membros}
    if congregacao_id not in permitidas and not sessao.usuario.super_admin:
        return False
    repo.trocar_congregacao_da_sessao(conn, hash_token_sessao(token), congregacao_id)
    return True


def encerrar_sessao(conn, token: Optional[str]) -> None:
    if token:
        repo.remover_sessao(conn, hash_token_sessao(token))


# === Solicitação de acesso ==================================================

class ResultadoSolicitacao(str, Enum):
    CRIADA = "CRIADA"
    JA_PENDENTE = "JA_PENDENTE"
    JA_TEM_ACESSO = "JA_TEM_ACESSO"
    DADOS_INVALIDOS = "DADOS_INVALIDOS"


@dataclass
class PedidoDeAcesso:
    resultado: ResultadoSolicitacao
    solicitacao: Optional[Solicitacao] = None


def solicitar_acesso(
    conn,
    email: str,
    nome: str,
    congregacao_id: Optional[int],
    congregacao_nova: str,
    mensagem: str,
) -> PedidoDeAcesso:
    email = repo.normalizar_email(email)
    if "@" not in email or "." not in email.split("@")[-1]:
        return PedidoDeAcesso(ResultadoSolicitacao.DADOS_INVALIDOS)
    if congregacao_id is None and not congregacao_nova.strip():
        return PedidoDeAcesso(ResultadoSolicitacao.DADOS_INVALIDOS)

    usuario = repo.obter_usuario_por_email(conn, email)
    if usuario and congregacao_id is not None:
        if repo.obter_papel(conn, usuario.id, congregacao_id) is not None:
            return PedidoDeAcesso(ResultadoSolicitacao.JA_TEM_ACESSO)

    solicitacao = repo.criar_solicitacao(
        conn, email, nome, congregacao_id, congregacao_nova, mensagem
    )
    if solicitacao is None:
        return PedidoDeAcesso(ResultadoSolicitacao.JA_PENDENTE)

    _avisar_aprovadores(conn, solicitacao)
    return PedidoDeAcesso(ResultadoSolicitacao.CRIADA, solicitacao)


def _avisar_aprovadores(conn, solicitacao: Solicitacao) -> None:
    """Avisa quem pode decidir: os super-admins e, quando o pedido é para uma
    congregação existente, os administradores dela. Falha de e-mail não pode
    derrubar o pedido — ele já está gravado e aparece no painel de qualquer
    jeito."""
    # O formulário de solicitação é público: sem um teto, alguém variando o
    # e-mail geraria um aviso por pedido e entupiria a caixa do administrador
    # (e a cota do provedor). Passando do teto, os pedidos continuam sendo
    # gravados e aparecendo no painel — só o aviso por e-mail para.
    if repo.contar_solicitacoes_recentes(conn) > config.SOLICITACOES_AVISO_MAX_POR_HORA:
        logger.warning(
            "muitas solicitações na última hora; avisos por e-mail suspensos "
            "(os pedidos continuam no painel)"
        )
        return

    destinatarios = {
        u.email for u in repo.listar_usuarios(conn) if u.super_admin and u.ativo
    }
    if solicitacao.congregacao_id is not None:
        for usuario, papel in repo.listar_membros_da_congregacao(conn, solicitacao.congregacao_id):
            if papel is Papel.ADMIN and usuario.ativo:
                destinatarios.add(usuario.email)

    alvo = solicitacao.congregacao_nome or solicitacao.congregacao_nome_sugerida or "(nova congregação)"
    for destinatario in destinatarios:
        try:
            email_envio.enviar_aviso_de_solicitacao(
                destinatario, solicitacao.nome, solicitacao.email, alvo
            )
        except email_envio.FalhaNoEnvio as e:
            logger.warning("não consegui avisar %s da solicitação %s: %s",
                           destinatario, solicitacao.id, e)


# === Decisão sobre a solicitação ============================================

def pode_decidir(conn, sessao: SessaoAtual, solicitacao: Solicitacao) -> bool:
    if sessao.usuario.super_admin:
        return True
    # pedido de congregação NOVA só o super-admin resolve — é ele quem decide
    # se a instalação ganha mais uma congregação.
    if solicitacao.congregacao_id is None:
        return False
    return repo.obter_papel(conn, sessao.usuario.id, solicitacao.congregacao_id) is Papel.ADMIN


@dataclass
class Aprovacao:
    ok: bool
    motivo: str = ""
    congregacao: Optional[Congregacao] = None


def aprovar_solicitacao(
    conn, solicitacao_id: int, papel: Papel, aprovador: SessaoAtual, observacao: str = ""
) -> Aprovacao:
    solicitacao = repo.obter_solicitacao(conn, solicitacao_id)
    if solicitacao is None:
        return Aprovacao(False, "Solicitação não encontrada.")
    if solicitacao.status is not StatusSolicitacao.PENDENTE:
        return Aprovacao(False, "Esta solicitação já foi decidida.")
    if not pode_decidir(conn, aprovador, solicitacao):
        return Aprovacao(False, "Você não tem permissão para decidir esta solicitação.")

    congregacao_id = solicitacao.congregacao_id
    congregacao: Optional[Congregacao] = None
    criou_congregacao = False

    if congregacao_id is None:
        # importado aqui para evitar ciclo (migrations importa repositórios)
        from app.db.migrations import preparar_congregacao

        congregacao = repo.criar_congregacao(conn, solicitacao.congregacao_nome_sugerida)
        congregacao_id = congregacao.id
        preparar_congregacao(conn, congregacao_id)
        criou_congregacao = True
        # quem pediu uma congregação nova vira o administrador dela: não há
        # mais ninguém lá dentro para administrá-la.
        papel = Papel.ADMIN
    else:
        congregacao = repo.obter_congregacao(conn, congregacao_id)
        if congregacao is None:
            return Aprovacao(False, "A congregação da solicitação não existe mais.")

    usuario = repo.obter_ou_criar_usuario(conn, solicitacao.email, solicitacao.nome)
    repo.definir_membro(conn, usuario.id, congregacao_id, papel)
    repo.decidir_solicitacao(
        conn, solicitacao_id, StatusSolicitacao.APROVADA, aprovador.usuario.id, observacao
    )

    try:
        email_envio.enviar_aviso_de_aprovacao(usuario.email, congregacao.nome, papel.value)
    except email_envio.FalhaNoEnvio as e:
        logger.warning("acesso aprovado mas não consegui avisar %s: %s", usuario.email, e)

    if criou_congregacao:
        logger.info("congregação %s criada ao aprovar a solicitação %s",
                    congregacao.slug, solicitacao_id)
    return Aprovacao(True, congregacao=congregacao)


def recusar_solicitacao(
    conn, solicitacao_id: int, recusador: SessaoAtual, observacao: str = ""
) -> Aprovacao:
    solicitacao = repo.obter_solicitacao(conn, solicitacao_id)
    if solicitacao is None:
        return Aprovacao(False, "Solicitação não encontrada.")
    if solicitacao.status is not StatusSolicitacao.PENDENTE:
        return Aprovacao(False, "Esta solicitação já foi decidida.")
    if not pode_decidir(conn, recusador, solicitacao):
        return Aprovacao(False, "Você não tem permissão para decidir esta solicitação.")

    repo.decidir_solicitacao(
        conn, solicitacao_id, StatusSolicitacao.RECUSADA, recusador.usuario.id, observacao
    )
    alvo = solicitacao.congregacao_nome or solicitacao.congregacao_nome_sugerida
    try:
        email_envio.enviar_aviso_de_recusa(solicitacao.email, alvo, observacao)
    except email_envio.FalhaNoEnvio as e:
        logger.warning("solicitação recusada mas não consegui avisar %s: %s",
                       solicitacao.email, e)
    return Aprovacao(True)
