from datetime import date

from app.engine.calendar_utils import SlotInstancia
from app.engine.scoring import chave_prioridade
from app.engine.sorteio import ContextoSorteio, gerar_escala
from app.models import Origem


def _instancia(dia: int, slot_id: str, requer_dirigente: bool = False) -> SlotInstancia:
    return SlotInstancia(
        data=date(2026, 7, dia), slot_id=slot_id, dia_semana="QUARTA", requer_dirigente=requer_dirigente
    )


def _contexto_basico(**overrides) -> ContextoSorteio:
    # Helper local (nao reusa o de test_sorteio.py) porque ContextoSorteio ganhou
    # o campo obrigatorio `conjuge_de` no contrato do casal.
    base = dict(
        genero_por_pessoa={},
        ativos=set(),
        disponibilidade_slot={},
        fixos_por_slot={},
        ultima_designacao={},
        total_designacoes={},
        duplas_recentes=set(),
        conjuge_de={},
        dirigentes_ativos=set(),
        disponibilidade_dirigente_slot={},
        ultima_designacao_dirigente={},
        total_designacoes_dirigente={},
    )
    base.update(overrides)
    return ContextoSorteio(**base)


def test_casal_misto_pode_ser_formado_pelo_sorteio():
    # Marido (M) + esposa (F): sao a unica dupla possivel neste slot; como sao casal,
    # o sorteio pode forma-los apesar dos generos diferentes (Origem.SORTEIO).
    ctx = _contexto_basico(
        genero_por_pessoa={1: "M", 2: "F"},
        ativos={1, 2},
        disponibilidade_slot={"SLOT_A": {1, 2}},
        conjuge_de={1: 2, 2: 1},
    )
    resultado = gerar_escala([_instancia(1, "SLOT_A")], ctx, "2026-07", date(2026, 7, 1))
    desig = resultado.designacoes[0]

    assert {desig.pessoa_id_1, desig.pessoa_id_2} == {1, 2}
    assert desig.origem == Origem.SORTEIO
    # sem aviso critico: a dupla casal e uma dupla valida
    assert not any(a.nivel == "critico" for a in resultado.avisos)


def test_casal_nao_e_forcado_dupla_de_mesmo_genero_ainda_pode_ocorrer():
    # A esposa (2) faz casal com o marido (1), MAS ha duas outras mulheres (3, 4).
    # O casal e apenas mais uma opcao; o sorteio pode escolher uma dupla F+F.
    # Aqui: pessoas 3 e 4 tem prioridade maxima (nunca serviram / servem ha mais tempo)
    # e o marido (1) foi rebaixado (serviu recentemente e muito), entao o resultado
    # esperado e a dupla de mesmo genero {3,4} ao inves do casal {1,2}.
    ctx = _contexto_basico(
        genero_por_pessoa={1: "M", 2: "F", 3: "F", 4: "F"},
        ativos={1, 2, 3, 4},
        disponibilidade_slot={"SLOT_A": {1, 2, 3, 4}},
        conjuge_de={1: 2, 2: 1},
        ultima_designacao={1: "2026-06-30", 2: "2026-06-30"},
        total_designacoes={1: 50, 2: 50},
    )
    resultado = gerar_escala([_instancia(1, "SLOT_A")], ctx, "2026-07", date(2026, 7, 1))
    desig = resultado.designacoes[0]

    dupla = {desig.pessoa_id_1, desig.pessoa_id_2}
    generos = {ctx.genero_por_pessoa[p] for p in dupla}
    # dupla escolhida e de mesmo genero (casal nao foi forcado)
    assert len(generos) == 1
    assert dupla == {3, 4}


def test_bug4_pessoa_fixa_inativa_nao_e_escalada_e_gera_aviso_critico():
    # Pessoa 1 e fixa no slot mas esta INATIVA (nao esta em ctx.ativos).
    # Nao deve ser escalada e o slot deve acabar sem par valido -> aviso critico.
    ctx = _contexto_basico(
        genero_por_pessoa={1: "F", 2: "F"},
        ativos={2},  # 1 esta inativa
        disponibilidade_slot={"SLOT_A": {1, 2}},
        fixos_por_slot={"SLOT_A": (1, None)},
    )
    resultado = gerar_escala([_instancia(1, "SLOT_A")], ctx, "2026-07", date(2026, 7, 1))
    desig = resultado.designacoes[0]

    # a pessoa fixa inativa nao pode compor a designacao final
    # AJUSTAR SE ASSINATURA DIVERGIR: dependendo da regra, o fixo inativo pode
    # zerar o slot inteiro (VAZIO) em vez de so nao entrar no par.
    assert desig.pessoa_id_1 != 1 and desig.pessoa_id_2 != 1
    assert any(a.nivel == "critico" for a in resultado.avisos)


def test_bug8_chave_prioridade_clamp_em_zero_para_ultima_str_no_futuro():
    # ultima designacao NO FUTURO (relogio errado / mes fechado fora de ordem):
    # nao pode produzir dias_sem_servir negativo. Clamp em 0 => primeira_chave == 0,
    # igual a quem serviu exatamente hoje.
    hoje = date(2026, 7, 1)
    chave_futuro = chave_prioridade(1, {1: "2026-12-31"}, {1: 0}, hoje)
    chave_hoje = chave_prioridade(2, {2: hoje.isoformat()}, {2: 0}, hoje)

    assert chave_futuro[0] == 0  # nao negativo
    assert chave_futuro[0] == chave_hoje[0]
    # sanidade: quem nunca serviu tem prioridade maxima (-inf), abaixo de todos
    chave_nunca = chave_prioridade(3, {}, {}, hoje)
    assert chave_nunca[0] < chave_futuro[0]
