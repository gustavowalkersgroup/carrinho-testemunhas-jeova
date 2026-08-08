"""O banco isola as congregações sozinho, sem depender do código da aplicação.

Estes testes falam direto com os repositórios, sem passar por rota nenhuma:
provam que o Row Level Security do Postgres sustenta o isolamento mesmo que
uma consulta esqueça o filtro — que é a razão de ele existir.
"""

from datetime import date

import pytest

from tests_web.conftest import criar_congregacao

from app.db import postgres
from app.models import BloqueioIn, FixoIn, Genero, PessoaIn
from app.repositories import (
    bloqueios_repo,
    configuracoes_repo,
    fixos_repo,
    historico_repo,
    pessoas_repo,
    saida_repo,
    slots_repo,
)
from app.services import cadastro_service, escala_service


@pytest.fixture
def duas(banco_limpo):
    ids = {"a": criar_congregacao("Congregação A"), "b": criar_congregacao("Congregação B")}
    for chave, cid in ids.items():
        with postgres.get_connection(cid) as conn:
            for i in range(6):
                pessoas_repo.criar(conn, PessoaIn(
                    nome=f"Irmão {i} da {chave.upper()}",
                    genero=Genero.M if i % 2 == 0 else Genero.F,
                    pode_dirigir=(i < 2),
                ))
            slots = [s.slot_id for s in slots_repo.listar(conn, somente_ativos=True)]
            for p in pessoas_repo.listar(conn):
                cadastro_service.definir_disponibilidade_pessoa(conn, p.id, slots)
            configuracoes_repo.definir(conn, "nome_congregacao", f"Congregação {chave.upper()}")
            bloqueios_repo.criar(conn, BloqueioIn(
                data_inicio=date(2026, 9, 1), data_fim=date(2026, 9, 2), motivo=chave))
    return ids


def test_cada_congregacao_ve_so_as_proprias_pessoas(duas):
    with postgres.get_connection(duas["a"]) as conn:
        nomes_a = [p.nome for p in pessoas_repo.listar(conn)]
    with postgres.get_connection(duas["b"]) as conn:
        nomes_b = [p.nome for p in pessoas_repo.listar(conn)]

    assert len(nomes_a) == 6 and len(nomes_b) == 6
    assert all("da A" in n for n in nomes_a)
    assert all("da B" in n for n in nomes_b)


def test_configuracoes_e_bloqueios_tambem_sao_separados(duas):
    with postgres.get_connection(duas["a"]) as conn:
        assert configuracoes_repo.obter(conn, "nome_congregacao") == "Congregação A"
        assert [b.motivo for b in bloqueios_repo.listar(conn)] == ["a"]
    with postgres.get_connection(duas["b"]) as conn:
        assert configuracoes_repo.obter(conn, "nome_congregacao") == "Congregação B"
        assert [b.motivo for b in bloqueios_repo.listar(conn)] == ["b"]


def test_sem_congregacao_declarada_nao_volta_nada(duas):
    """A garantia de falhar fechando: uma consulta que rodasse sem contexto de
    congregação devolve zero linhas, nunca as linhas de outra pessoa."""
    with postgres.get_connection(None) as conn:
        assert pessoas_repo.listar(conn) == []
        assert slots_repo.listar(conn) == []
        assert bloqueios_repo.listar(conn) == []
        assert configuracoes_repo.obter_todas(conn) == {}


def test_sem_congregacao_declarada_nao_grava(duas):
    with pytest.raises(Exception):
        with postgres.get_connection(None) as conn:
            pessoas_repo.criar(conn, PessoaIn(nome="Fantasma", genero=Genero.M))

    with postgres.get_connection(duas["a"]) as conn:
        assert "Fantasma" not in {p.nome for p in pessoas_repo.listar(conn)}


def test_super_admin_enxerga_todas(duas):
    with postgres.get_connection(None, super_admin=True) as conn:
        assert len(pessoas_repo.listar(conn)) == 12


def test_historico_de_uma_nao_aparece_na_outra(duas):
    with postgres.get_connection(duas["a"]) as conn:
        escala = escala_service.gerar_rascunho(conn, 2026, 9, date(2026, 8, 20))
        assert escala.designacoes
        escala_service.fechar_mes(conn, "2026-09")
        assert historico_repo.total_designacoes_por_pessoa(conn)

    with postgres.get_connection(duas["b"]) as conn:
        assert historico_repo.total_designacoes_por_pessoa(conn) == {}
        assert historico_repo.buscar_por_mes(conn, "2026-09") == []
        assert historico_repo.ultima_designacao_por_pessoa(conn) == {}


def test_dois_congregacoes_podem_usar_o_mesmo_identificador_de_horario(duas):
    """`slot_id` é texto escolhido pelo usuário; duas congregações usando
    "SEG_MANHA_A" não podem colidir — a chave primária inclui a congregação."""
    with postgres.get_connection(duas["a"]) as conn:
        ids_a = {s.slot_id for s in slots_repo.listar(conn)}
    with postgres.get_connection(duas["b"]) as conn:
        ids_b = {s.slot_id for s in slots_repo.listar(conn)}
    assert ids_a and ids_a == ids_b  # mesmos identificadores, dados separados


def test_conjuge_de_outra_congregacao_e_recusado_pelo_banco(duas):
    with postgres.get_connection(duas["a"]) as conn:
        pessoa_a = pessoas_repo.listar(conn)[0]
    with postgres.get_connection(duas["b"]) as conn:
        pessoa_b = pessoas_repo.listar(conn)[0]

    with pytest.raises(Exception):
        with postgres.get_connection(duas["a"]) as conn:
            pessoas_repo.set_conjuge(conn, pessoa_a.id, pessoa_b.id)


def test_fixo_apontando_para_pessoa_de_outra_congregacao_e_recusado(duas):
    with postgres.get_connection(duas["b"]) as conn:
        pessoa_b = pessoas_repo.listar(conn)[0]

    with pytest.raises(Exception):
        with postgres.get_connection(duas["a"]) as conn:
            slot = slots_repo.listar(conn, somente_ativos=True)[0]
            fixos_repo.criar(conn, FixoIn(
                slot_id=slot.slot_id, pessoa_id_1=pessoa_b.id,
                vigencia_inicio=date(2020, 1, 1)))


def test_saidas_de_campo_ficam_na_propria_congregacao(duas):
    with postgres.get_connection(duas["a"]) as conn:
        saidas = saida_repo.listar(conn, somente_ativos=True)
        dirigente = pessoas_repo.listar_dirigentes(conn)[0]
        saida_repo.definir_disponibilidade_do_dirigente(conn, dirigente.id, [saidas[0].saida_id])
        assert saida_repo.listar_saidas_do_dirigente(conn, dirigente.id) == [saidas[0].saida_id]

    with postgres.get_connection(duas["b"]) as conn:
        assert saida_repo.listar_saidas_do_dirigente(conn, dirigente.id) == []


def test_apagar_congregacao_leva_junto_os_dados_dela(duas):
    from app.auth import repo

    with postgres.get_connection(duas["a"]) as conn:
        escala_service.gerar_rascunho(conn, 2026, 9, date(2026, 8, 20))

    with postgres.get_connection(super_admin=True) as conn:
        assert repo.remover_congregacao(conn, duas["a"])

    with postgres.get_connection(None, super_admin=True) as conn:
        # sobraram só as 6 pessoas da congregação B
        assert len(pessoas_repo.listar(conn)) == 6
        assert historico_repo.buscar_por_mes(conn, "2026-09") == []

    with postgres.get_connection(duas["b"]) as conn:
        assert len(pessoas_repo.listar(conn)) == 6
