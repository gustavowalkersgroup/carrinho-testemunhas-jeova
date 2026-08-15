"""Congregação de demonstração: dados fictícios, navegável sem login em
`/demo` (ver `app/web/auth_routes.py`).

Só existe no modo WEB (multi-tenant). É uma congregação como qualquer outra —
o isolamento por Row Level Security garante que ela nunca vê nem é vista
pelas congregações reais. Reseta periodicamente (ver `resetar_demo`, chamada
pelo cron em `POST /api/automacao/resetar-demo`) apagando a congregação
inteira (cascata no schema) e recriando os dados fictícios do zero.
"""

from __future__ import annotations

import random
from datetime import date

from app.auth import repo as auth_repo
from app.auth.models import Congregacao, Papel, Usuario
from app.db.connection import get_connection
from app.db.migrations import preparar_congregacao
from app.models import Pessoa, PessoaIn
from app.repositories import configuracoes_repo, pessoas_repo, slots_repo
from app.services import cadastro_service, escala_service

NOME_CONGREGACAO_DEMO = "Demonstração"
SLUG_CONGREGACAO_DEMO = "demonstracao"
EMAIL_USUARIO_DEMO = "demo@escaladocarrinho.local"

# 10 casais (a dupla mista escapa da regra de "mesmo gênero" do sorteio, como
# no app real) + 20 solteiros -- 40 pessoas ao todo.
_CASAIS: list[tuple[str, str]] = [
    ("Ricardo", "Fernanda"),
    ("Marcos", "Juliana"),
    ("Eduardo", "Patrícia"),
    ("Rodrigo", "Camila"),
    ("Fábio", "Vanessa"),
    ("Alexandre", "Renata"),
    ("Thiago", "Larissa"),
    ("Rafael", "Débora"),
    ("Leonardo", "Aline"),
    ("Marcelo", "Tatiane"),
]
_SOLTEIROS_M = [
    "Gabriel", "Vinícius", "Matheus", "Felipe", "Otávio",
    "Caio", "Bruno", "Diego", "Henrique", "Rogério",
]
_SOLTEIROS_F = [
    "Beatriz", "Priscila", "Vivian", "Cristiane", "Daniela",
    "Simone", "Michele", "Fabiana", "Regina", "Sueli",
]
# Quem serve como dirigente de campo no pool de exemplo.
_DIRIGENTES_DEMO = {"Gabriel", "Vinícius", "Matheus", "Felipe", "Ricardo", "Marcos"}


def _obter_ou_criar_usuario_demo(conn) -> Usuario:
    usuario = auth_repo.obter_usuario_por_email(conn, EMAIL_USUARIO_DEMO)
    if usuario is not None:
        return usuario
    return auth_repo.criar_usuario(conn, EMAIL_USUARIO_DEMO, nome="Visitante da demonstração")


def _semear_pessoas(conn) -> None:
    slots_existentes = [s.slot_id for s in slots_repo.listar(conn, somente_ativos=True)]

    def sortear_slots() -> list[str]:
        if not slots_existentes:
            return []
        qtd = min(random.randint(2, 4), len(slots_existentes))
        return random.sample(slots_existentes, qtd)

    def criar(nome: str, genero: str) -> Pessoa:
        return pessoas_repo.criar(
            conn, PessoaIn(nome=nome, genero=genero, pode_dirigir=nome in _DIRIGENTES_DEMO)
        )

    for nome_m, nome_f in _CASAIS:
        slots_casal = sortear_slots()
        marido = criar(nome_m, "M")
        esposa = criar(nome_f, "F")
        cadastro_service.definir_disponibilidade_pessoa(conn, marido.id, slots_casal)
        cadastro_service.definir_disponibilidade_pessoa(conn, esposa.id, slots_casal)
        cadastro_service.definir_conjuge(conn, marido.id, esposa.id)

    for nome in _SOLTEIROS_M:
        pessoa = criar(nome, "M")
        cadastro_service.definir_disponibilidade_pessoa(conn, pessoa.id, sortear_slots())

    for nome in _SOLTEIROS_F:
        pessoa = criar(nome, "F")
        cadastro_service.definir_disponibilidade_pessoa(conn, pessoa.id, sortear_slots())


def _gerar_escalas_iniciais(conn) -> None:
    hoje = date.today()
    for referencia in (hoje, date(hoje.year + (hoje.month // 12), hoje.month % 12 + 1, 1)):
        try:
            escala_service.gerar_rascunho(conn, referencia.year, referencia.month, hoje)
        except ValueError:
            # sem gente suficiente pra algum horário específico -- a demo
            # continua com o que deu pra sortear, sem quebrar o seed inteiro.
            pass


def garantir_demo_congregacao(conn) -> Congregacao:
    """Idempotente: cria a congregação de demonstração na primeira chamada,
    devolve a existente nas seguintes."""
    existente = auth_repo.obter_congregacao_por_slug(conn, SLUG_CONGREGACAO_DEMO)
    if existente is not None:
        usuario = _obter_ou_criar_usuario_demo(conn)
        auth_repo.definir_membro(conn, usuario.id, existente.id, Papel.EDITOR)
        return existente

    congregacao = auth_repo.criar_congregacao(conn, NOME_CONGREGACAO_DEMO, "")
    preparar_congregacao(conn, congregacao.id)

    conn.definir_congregacao(congregacao.id)
    try:
        _semear_pessoas(conn)
        configuracoes_repo.definir(conn, "wizard_concluido", "1")
        configuracoes_repo.definir(conn, "nome_congregacao", "Congregação Demonstração")
        _gerar_escalas_iniciais(conn)
    finally:
        conn.definir_congregacao(None)

    usuario = _obter_ou_criar_usuario_demo(conn)
    auth_repo.definir_membro(conn, usuario.id, congregacao.id, Papel.EDITOR)
    return congregacao


def resetar_demo() -> None:
    """Apaga a congregação de demonstração inteira (cascata no schema: todas
    as pessoas, escalas, fixos etc. dela) e recria do zero. `super_admin=True`
    de propósito: sem sessão de usuário aqui, e o RLS derruba a cascata se
    `current_congregacao()`/`is_super_admin()` não abrirem caminho para ela."""
    with get_connection(super_admin=True) as conn:
        existente = auth_repo.obter_congregacao_por_slug(conn, SLUG_CONGREGACAO_DEMO)
        if existente is not None:
            auth_repo.remover_congregacao(conn, existente.id)
        garantir_demo_congregacao(conn)
