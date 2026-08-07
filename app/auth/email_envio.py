"""Envio de e-mail com três estratégias, na ordem: Resend, SMTP, log.

Resend vem primeiro porque é HTTP: em ambiente serverless (Vercel) as portas
de SMTP costumam estar fechadas e uma conexão SMTP demorada custa tempo de
execução. SMTP fica como alternativa para quem já tem um servidor próprio.

O modo "log" não envia nada — só escreve o conteúdo no log da aplicação. Ele
existe para o primeiro acesso de uma instalação recém-criada, quando ainda não
há provedor configurado: o super-admin lê o código no painel da Vercel e entra.
Quem decide se esse caminho é aceitável é `auth/service.py`, que só o permite
para os e-mails listados em SUPER_ADMIN_EMAIL.
"""

from __future__ import annotations

import json
import logging
import smtplib
import urllib.error
import urllib.request
from email.message import EmailMessage

from app import config

logger = logging.getLogger("escala.email")

RESEND_ENDPOINT = "https://api.resend.com/emails"


class FalhaNoEnvio(Exception):
    pass


def enviar(destinatario: str, assunto: str, corpo_texto: str, corpo_html: str = "") -> str:
    """Devolve qual estratégia foi usada: "resend", "smtp" ou "log"."""
    if config.RESEND_API_KEY:
        _enviar_resend(destinatario, assunto, corpo_texto, corpo_html)
        return "resend"
    if config.SMTP_HOST and config.SMTP_USER:
        _enviar_smtp(destinatario, assunto, corpo_texto, corpo_html)
        return "smtp"
    _registrar_no_log(destinatario, assunto, corpo_texto)
    return "log"


def _enviar_resend(destinatario: str, assunto: str, texto: str, html: str) -> None:
    payload = {
        "from": config.EMAIL_REMETENTE,
        "to": [destinatario],
        "subject": assunto,
        "text": texto,
    }
    if html:
        payload["html"] = html

    requisicao = urllib.request.Request(
        RESEND_ENDPOINT,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {config.RESEND_API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(requisicao, timeout=10) as resposta:
            if resposta.status >= 300:
                raise FalhaNoEnvio(f"Resend respondeu {resposta.status}")
    except urllib.error.HTTPError as e:
        detalhe = e.read().decode("utf-8", "replace")[:300]
        raise FalhaNoEnvio(f"Resend respondeu {e.code}: {detalhe}") from e
    except urllib.error.URLError as e:
        raise FalhaNoEnvio(f"não foi possível falar com o Resend: {e.reason}") from e


def _enviar_smtp(destinatario: str, assunto: str, texto: str, html: str) -> None:
    mensagem = EmailMessage()
    mensagem["From"] = config.EMAIL_REMETENTE
    mensagem["To"] = destinatario
    mensagem["Subject"] = assunto
    mensagem.set_content(texto)
    if html:
        mensagem.add_alternative(html, subtype="html")

    try:
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=15) as servidor:
            servidor.starttls()
            servidor.login(config.SMTP_USER, config.SMTP_PASSWORD)
            servidor.send_message(mensagem)
    except (smtplib.SMTPException, OSError) as e:
        raise FalhaNoEnvio(f"falha no SMTP: {e}") from e


def _registrar_no_log(destinatario: str, assunto: str, texto: str) -> None:
    logger.warning(
        "SEM PROVEDOR DE E-MAIL CONFIGURADO — mensagem não enviada.\n"
        "Para: %s\nAssunto: %s\n%s",
        destinatario,
        assunto,
        texto,
    )


# === Mensagens ==============================================================

def _rodape() -> str:
    if config.APP_BASE_URL:
        return f"\n\n—\nEscala do Carrinho\n{config.APP_BASE_URL}"
    return "\n\n—\nEscala do Carrinho"


def enviar_codigo_login(destinatario: str, codigo: str) -> str:
    assunto = f"{codigo} é o seu código de acesso"
    texto = (
        f"Seu código de acesso é: {codigo}\n\n"
        f"Ele vale por {config.CODIGO_LOGIN_VALIDADE_MINUTOS} minutos e só pode ser usado uma vez.\n\n"
        "Se você não pediu este código, pode ignorar esta mensagem — sem o código "
        "ninguém entra na sua conta." + _rodape()
    )
    html = f"""
    <div style="font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;max-width:480px">
      <p>Seu código de acesso é:</p>
      <p style="font-size:34px;letter-spacing:9px;font-weight:700;margin:18px 0">{codigo}</p>
      <p style="color:#555">Vale por {config.CODIGO_LOGIN_VALIDADE_MINUTOS} minutos e só pode ser usado uma vez.</p>
      <p style="color:#555">Se você não pediu este código, pode ignorar esta mensagem.</p>
    </div>
    """
    return enviar(destinatario, assunto, texto, html)


def enviar_aviso_de_solicitacao(destinatario: str, nome: str, email: str, congregacao: str) -> str:
    assunto = "Nova solicitação de acesso"
    link = f"{config.APP_BASE_URL}/admin/solicitacoes" if config.APP_BASE_URL else "/admin/solicitacoes"
    texto = (
        f"{nome or email} pediu acesso a: {congregacao}\n\n"
        f"E-mail: {email}\n\n"
        f"Para aprovar ou recusar, abra o painel: {link}" + _rodape()
    )
    return enviar(destinatario, assunto, texto)


def enviar_aviso_de_aprovacao(destinatario: str, congregacao: str, papel: str) -> str:
    assunto = "Seu acesso foi aprovado"
    link = f"{config.APP_BASE_URL}/entrar" if config.APP_BASE_URL else "/entrar"
    texto = (
        f"Seu acesso à congregação {congregacao} foi aprovado (perfil: {papel}).\n\n"
        f"Para entrar, acesse {link} e informe este mesmo e-mail — "
        "você receberá um código de 6 dígitos para confirmar." + _rodape()
    )
    return enviar(destinatario, assunto, texto)


def enviar_aviso_de_recusa(destinatario: str, congregacao: str, observacao: str) -> str:
    assunto = "Sobre a sua solicitação de acesso"
    texto = f"Sua solicitação de acesso a {congregacao} não foi aprovada."
    if observacao:
        texto += f"\n\nObservação de quem avaliou: {observacao}"
    return enviar(destinatario, assunto, texto + _rodape())
