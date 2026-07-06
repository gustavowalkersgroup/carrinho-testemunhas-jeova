from dataclasses import dataclass
from datetime import date

from app.engine.calendar_utils import SlotInstancia
from app.engine.sorteio import ContextoSorteio, gerar_escala
from app.models import Origem


def _instancia(dia: int, slot_id: str, requer_dirigente: bool = False) -> SlotInstancia:
    return SlotInstancia(data=date(2026, 7, dia), slot_id=slot_id, dia_semana="QUARTA", requer_dirigente=requer_dirigente)


def _contexto_basico(**overrides) -> ContextoSorteio:
    base = dict(
        genero_por_pessoa={},
        ativos=set(),
        disponibilidade_slot={},
        fixos_por_slot={},
        ultima_designacao={},
        total_designacoes={},
        duplas_recentes=set(),
        dirigentes_ativos=set(),
        disponibilidade_dirigente_slot={},
        ultima_designacao_dirigente={},
        total_designacoes_dirigente={},
    )
    base.update(overrides)
    return ContextoSorteio(**base)


def test_pessoa_fixa_preenche_slot_e_parceira_e_sorteada():
    ctx = _contexto_basico(
        genero_por_pessoa={1: "F", 2: "F", 3: "F"},
        ativos={1, 2, 3},
        disponibilidade_slot={"SLOT_A": {1, 2, 3}},
        fixos_por_slot={"SLOT_A": (1, None)},
    )
    resultado = gerar_escala([_instancia(1, "SLOT_A")], ctx, "2026-07", date(2026, 7, 1))

    desig = resultado.designacoes[0]
    assert desig.pessoa_id_1 == 1
    assert desig.pessoa_id_2 in (2, 3)
    assert desig.origem == Origem.FIXO


def test_pessoa_fixa_nao_e_sorteada_de_novo_em_outro_slot():
    ctx = _contexto_basico(
        genero_por_pessoa={1: "F", 2: "F", 3: "F", 4: "F"},
        ativos={1, 2, 3, 4},
        disponibilidade_slot={"SLOT_A": {1, 2, 3, 4}, "SLOT_B": {1, 2, 3, 4}},
        fixos_por_slot={"SLOT_A": (1, None)},
    )
    resultado = gerar_escala(
        [_instancia(1, "SLOT_A"), _instancia(2, "SLOT_B")], ctx, "2026-07", date(2026, 7, 1)
    )
    slot_b = next(d for d in resultado.designacoes if d.slot_id == "SLOT_B")
    assert 1 not in (slot_b.pessoa_id_1, slot_b.pessoa_id_2)


def test_dupla_sempre_do_mesmo_genero():
    ctx = _contexto_basico(
        genero_por_pessoa={1: "M", 2: "F", 3: "F"},
        ativos={1, 2, 3},
        disponibilidade_slot={"SLOT_A": {1, 2, 3}},
    )
    resultado = gerar_escala([_instancia(1, "SLOT_A")], ctx, "2026-07", date(2026, 7, 1))
    desig = resultado.designacoes[0]
    assert desig.pessoa_id_1 is not None and desig.pessoa_id_2 is not None
    generos = {ctx.genero_por_pessoa[desig.pessoa_id_1], ctx.genero_por_pessoa[desig.pessoa_id_2]}
    assert len(generos) == 1


def test_prioriza_quem_esta_ha_mais_tempo_sem_servir():
    ctx = _contexto_basico(
        genero_por_pessoa={1: "F", 2: "F", 3: "F", 4: "F"},
        ativos={1, 2, 3, 4},
        disponibilidade_slot={"SLOT_A": {1, 2, 3, 4}},
        ultima_designacao={1: "2026-01-01", 2: "2026-06-01", 3: "2026-06-15", 4: "2026-06-20"},
    )
    resultado = gerar_escala([_instancia(1, "SLOT_A")], ctx, "2026-07", date(2026, 7, 1))
    desig = resultado.designacoes[0]
    # pessoa 1 nunca... na verdade serviu há mais tempo (jan) deve vir primeiro
    assert desig.pessoa_id_1 == 1 or desig.pessoa_id_2 == 1


def test_evita_repetir_dupla_recente_quando_ha_alternativa():
    ctx = _contexto_basico(
        genero_por_pessoa={1: "F", 2: "F", 3: "F", 4: "F"},
        ativos={1, 2, 3, 4},
        disponibilidade_slot={"SLOT_A": {1, 2, 3, 4}},
        duplas_recentes={frozenset((1, 2))},
    )
    resultado = gerar_escala([_instancia(1, "SLOT_A")], ctx, "2026-07", date(2026, 7, 1))
    desig = resultado.designacoes[0]
    dupla = frozenset((desig.pessoa_id_1, desig.pessoa_id_2))
    assert dupla != frozenset((1, 2))
    assert desig.origem == Origem.SORTEIO


def test_fallback_repete_dupla_quando_e_a_unica_opcao():
    ctx = _contexto_basico(
        genero_por_pessoa={1: "F", 2: "F"},
        ativos={1, 2},
        disponibilidade_slot={"SLOT_A": {1, 2}},
        duplas_recentes={frozenset((1, 2))},
    )
    resultado = gerar_escala([_instancia(1, "SLOT_A")], ctx, "2026-07", date(2026, 7, 1))
    desig = resultado.designacoes[0]
    assert {desig.pessoa_id_1, desig.pessoa_id_2} == {1, 2}
    assert desig.origem == Origem.FALLBACK_PAR_REPETIDO
    assert resultado.avisos  # deve ter gerado aviso


def test_fallback_duplica_pessoa_no_mes_quando_pool_e_pequeno():
    ctx = _contexto_basico(
        genero_por_pessoa={1: "F", 2: "F"},
        ativos={1, 2},
        disponibilidade_slot={"SLOT_A": {1, 2}, "SLOT_B": {1, 2}},
    )
    resultado = gerar_escala(
        [_instancia(1, "SLOT_A"), _instancia(2, "SLOT_B")], ctx, "2026-07", date(2026, 7, 1)
    )
    origens = {d.slot_id: d.origem for d in resultado.designacoes}
    # o segundo slot não tem mais gente nova disponível -> repete alguém do primeiro slot
    assert origens["SLOT_B"] == Origem.FALLBACK_DUPLICADO


def test_slot_fica_vazio_com_aviso_critico_quando_nao_ha_ninguem():
    ctx = _contexto_basico(
        genero_por_pessoa={1: "F"},
        ativos={1},
        disponibilidade_slot={"SLOT_A": {1}},
    )
    resultado = gerar_escala([_instancia(1, "SLOT_A")], ctx, "2026-07", date(2026, 7, 1))
    desig = resultado.designacoes[0]
    assert desig.pessoa_id_1 is None and desig.pessoa_id_2 is None
    assert desig.origem == Origem.VAZIO
    assert any(a.nivel == "critico" for a in resultado.avisos)


def test_nunca_lanca_excecao_mesmo_sem_candidatos_de_nenhum_genero():
    ctx = _contexto_basico(disponibilidade_slot={})
    resultado = gerar_escala([_instancia(1, "SLOT_INEXISTENTE")], ctx, "2026-07", date(2026, 7, 1))
    assert resultado.designacoes[0].origem == Origem.VAZIO


# NOTA: os testes de "dirigente sorteado no carrinho" foram removidos — no modelo
# novo o carrinho não sorteia mais dirigentes; a saída de campo é uma entidade
# separada. A cobertura equivalente está em tests/test_saidas.py.
def test_carrinho_nao_gera_mais_designacoes_dirigentes():
    ctx = _contexto_basico(
        genero_por_pessoa={1: "F", 2: "F"},
        ativos={1, 2},
        disponibilidade_slot={"SLOT_A": {1, 2}},
    )
    resultado = gerar_escala([_instancia(1, "SLOT_A", requer_dirigente=True)], ctx, "2026-07", date(2026, 7, 1))
    assert resultado.designacoes_dirigentes == []
