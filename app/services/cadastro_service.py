import sqlite3

from app import models
from app.repositories import dirigentes_repo, fixos_repo, pessoas_repo, slots_repo


def criar_fixo(conn: sqlite3.Connection, fixo: models.FixoIn) -> models.Fixo:
    if slots_repo.obter(conn, fixo.slot_id) is None:
        raise ValueError(f"Slot '{fixo.slot_id}' não existe.")
    if pessoas_repo.obter(conn, fixo.pessoa_id_1) is None:
        raise ValueError("Pessoa 1 do fixo não existe.")
    if fixo.pessoa_id_2 is not None:
        # dupla fixa em gênero misto é permitida aqui de propósito (ex.: casais que
        # sempre servem juntos) — só o sorteio aleatório exige mesmo gênero; um
        # fixo é uma decisão explícita do administrador, não um resultado do sorteio.
        if pessoas_repo.obter(conn, fixo.pessoa_id_2) is None:
            raise ValueError("Pessoa 2 do fixo não existe.")

    # BUG #6: rejeita fixar a mesma pessoa em dois slots com vigências que se
    # sobrepõem no tempo (independe do slot). Assume o helper novo do repo:
    #   fixos_repo.listar_vigentes_por_pessoa(conn, pessoa_id, vigencia_inicio, vigencia_fim)
    # que retorna os fixos vigentes da pessoa cujo período cruza [inicio, fim].
    pessoas_do_fixo = [fixo.pessoa_id_1]
    if fixo.pessoa_id_2 is not None:
        pessoas_do_fixo.append(fixo.pessoa_id_2)
    for pessoa_id in pessoas_do_fixo:
        sobrepostos = fixos_repo.listar_vigentes_por_pessoa(
            conn, pessoa_id, fixo.vigencia_inicio, fixo.vigencia_fim
        )
        if sobrepostos:
            raise ValueError(
                f"Pessoa (id {pessoa_id}) já é fixa em outro fixo vigente com "
                "período sobreposto. Encerre o fixo anterior antes de criar este."
            )

    return fixos_repo.criar(conn, fixo)


def definir_conjuge(conn: sqlite3.Connection, pessoa_id: int, conjuge_id: int | None) -> None:
    """Define (ou remove) o vínculo de cônjuge de forma SIMÉTRICA.

    - conjuge_id None: remove o vínculo de pessoa_id e do parceiro atual dela.
    - conjuge_id não-None: valida que ambas existem, impede autovínculo, e
      garante um cônjuge por pessoa — se pessoa_id ou conjuge_id já tinham
      OUTRO parceiro, esse parceiro antigo tem o vínculo limpo antes.

    Usa a primitiva pessoas_repo.set_conjuge(conn, pessoa_id, conjuge_id) que
    seta apenas UM lado; a simetria é montada aqui.
    """
    pessoa = pessoas_repo.obter(conn, pessoa_id)
    if pessoa is None:
        raise ValueError("Pessoa não existe.")

    parceiro_antigo_de_pessoa = getattr(pessoa, "conjuge_id", None)

    if conjuge_id is None:
        # limpa os dois lados do vínculo atual (se houver)
        if parceiro_antigo_de_pessoa is not None:
            pessoas_repo.set_conjuge(conn, parceiro_antigo_de_pessoa, None)
        pessoas_repo.set_conjuge(conn, pessoa_id, None)
        return

    if conjuge_id == pessoa_id:
        raise ValueError("Uma pessoa não pode ser cônjuge de si mesma.")

    conjuge = pessoas_repo.obter(conn, conjuge_id)
    if conjuge is None:
        raise ValueError("Cônjuge não existe.")

    # se qualquer um dos dois já tinha OUTRO parceiro, limpa esse lado órfão
    if parceiro_antigo_de_pessoa is not None and parceiro_antigo_de_pessoa != conjuge_id:
        pessoas_repo.set_conjuge(conn, parceiro_antigo_de_pessoa, None)
    parceiro_antigo_de_conjuge = getattr(conjuge, "conjuge_id", None)
    if parceiro_antigo_de_conjuge is not None and parceiro_antigo_de_conjuge != pessoa_id:
        pessoas_repo.set_conjuge(conn, parceiro_antigo_de_conjuge, None)

    # grava o vínculo nos dois sentidos
    pessoas_repo.set_conjuge(conn, pessoa_id, conjuge_id)
    pessoas_repo.set_conjuge(conn, conjuge_id, pessoa_id)


def definir_disponibilidade_pessoa(conn: sqlite3.Connection, pessoa_id: int, slot_ids: list[str]) -> None:
    from app.repositories import disponibilidades_repo

    if pessoas_repo.obter(conn, pessoa_id) is None:
        raise ValueError("Pessoa não existe.")
    for slot_id in slot_ids:
        if slots_repo.obter(conn, slot_id) is None:
            raise ValueError(f"Slot '{slot_id}' não existe.")
    disponibilidades_repo.definir_disponibilidade_da_pessoa(conn, pessoa_id, slot_ids)


def definir_disponibilidade_dirigente(conn: sqlite3.Connection, dirigente_id: int, slot_ids: list[str]) -> None:
    for slot_id in slot_ids:
        slot = slots_repo.obter(conn, slot_id)
        if slot is None:
            raise ValueError(f"Slot '{slot_id}' não existe.")
        if not slot.requer_dirigente:
            raise ValueError(f"Slot '{slot_id}' não é um slot com dirigente de campo.")
    dirigentes_repo.definir_disponibilidade_do_dirigente(conn, dirigente_id, slot_ids)
