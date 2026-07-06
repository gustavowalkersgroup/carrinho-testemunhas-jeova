from datetime import date

import pytest

from app import models
from app.models import Genero, PessoaIn, SlotTipoIn
from app.repositories import pessoas_repo, slots_repo
from app.services import cadastro_service


def _criar_pessoa(conn, nome: str, genero: str = "F") -> int:
    return pessoas_repo.criar(conn, PessoaIn(nome=nome, genero=Genero(genero))).id


def _criar_slot(conn, slot_id: str, requer_dirigente: bool = False) -> str:
    slots_repo.criar(
        conn,
        SlotTipoIn(
            slot_id=slot_id,
            dia_semana="QUARTA",
            periodo="TARDE",
            local="Zargon",
            ordem=1,
            requer_dirigente=requer_dirigente,
            vigencia_inicio=date(2026, 1, 1),
        ),
    )
    return slot_id


# --- definir_conjuge -------------------------------------------------------
# AJUSTAR SE ASSINATURA DIVERGIR: assumo cadastro_service.definir_conjuge(conn, pessoa_id, conjuge_id)
# com conjuge_id=None removendo o vinculo. A simetria e garantida na camada de servico
# (repo tem apenas set_conjuge, que seta um lado so).

def test_definir_conjuge_cria_vinculo_simetrico(conn):
    a = _criar_pessoa(conn, "Adelson", "M")
    b = _criar_pessoa(conn, "Cassilda", "F")

    cadastro_service.definir_conjuge(conn, a, b)

    assert pessoas_repo.obter(conn, a).conjuge_id == b
    assert pessoas_repo.obter(conn, b).conjuge_id == a


def test_definir_conjuge_trocar_limpa_o_antigo(conn):
    a = _criar_pessoa(conn, "Adelson", "M")
    b = _criar_pessoa(conn, "Cassilda", "F")
    c = _criar_pessoa(conn, "Berenice", "F")

    cadastro_service.definir_conjuge(conn, a, b)
    # troca: agora A e casado com C; o vinculo antigo com B deve ser desfeito
    cadastro_service.definir_conjuge(conn, a, c)

    assert pessoas_repo.obter(conn, a).conjuge_id == c
    assert pessoas_repo.obter(conn, c).conjuge_id == a
    # B ficou sem conjuge
    assert pessoas_repo.obter(conn, b).conjuge_id is None


def test_definir_conjuge_none_remove_vinculo(conn):
    a = _criar_pessoa(conn, "Adelson", "M")
    b = _criar_pessoa(conn, "Cassilda", "F")

    cadastro_service.definir_conjuge(conn, a, b)
    cadastro_service.definir_conjuge(conn, a, None)

    assert pessoas_repo.obter(conn, a).conjuge_id is None
    assert pessoas_repo.obter(conn, b).conjuge_id is None


def test_definir_conjuge_pessoa_nao_pode_ser_conjuge_de_si_mesma(conn):
    a = _criar_pessoa(conn, "Adelson", "M")

    with pytest.raises(ValueError):
        cadastro_service.definir_conjuge(conn, a, a)


# --- criar_fixo (BUG #6) ---------------------------------------------------

def test_criar_fixo_rejeita_pessoa_ja_fixa_em_slot_vigente_sobreposto(conn):
    # BUG #6: uma pessoa nao pode ser fixa em dois slots cujas vigencias se sobrepoem.
    slot_a = _criar_slot(conn, "SLOT_A")
    slot_b = _criar_slot(conn, "SLOT_B")
    p1 = _criar_pessoa(conn, "Adelson", "M")

    cadastro_service.criar_fixo(
        conn,
        models.FixoIn(slot_id=slot_a, pessoa_id_1=p1, vigencia_inicio=date(2026, 1, 1)),
    )

    # segundo fixo com vigencia sobreposta (aberta) para a mesma pessoa deve ser rejeitado
    with pytest.raises(ValueError):
        cadastro_service.criar_fixo(
            conn,
            models.FixoIn(slot_id=slot_b, pessoa_id_1=p1, vigencia_inicio=date(2026, 3, 1)),
        )


# --- definir_disponibilidade_dirigente (regra existente sem teste) ---------

def test_definir_disponibilidade_dirigente_rejeita_slot_sem_requer_dirigente(conn):
    slot = _criar_slot(conn, "SLOT_SEM_DIR", requer_dirigente=False)

    with pytest.raises(ValueError):
        cadastro_service.definir_disponibilidade_dirigente(conn, dirigente_id=1, slot_ids=[slot])


def test_definir_disponibilidade_dirigente_aceita_slot_com_requer_dirigente(conn):
    slot = _criar_slot(conn, "SLOT_COM_DIR", requer_dirigente=True)
    # cria dirigente para satisfazer eventual FK
    conn.execute("INSERT INTO dirigentes (id, nome, ativo) VALUES (1, 'Fulano', 1)")

    # nao deve levantar
    cadastro_service.definir_disponibilidade_dirigente(conn, dirigente_id=1, slot_ids=[slot])
