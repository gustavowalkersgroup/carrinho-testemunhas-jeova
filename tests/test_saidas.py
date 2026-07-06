"""Testes do modelo novo de Saída de Campo (separado do carrinho).

- Dirigente É uma pessoa (pool = ctx.dirigentes_pool).
- Saída de campo é separada do carrinho: seg-sábado, sorteia 1 dirigente por
  saída/dia, rodízio via ctx.ultima_saida/ctx.total_saidas, sem repetir na mesma semana ISO.
- gerar_saidas(instancias, ctx, mes, hoje) -> (designacoes, bloqueio, avisos), onde
  bloqueio[(data_iso, periodo)] = {pessoa_id}.
- BLOQUEIO dirigente<->carrinho: dirigente numa saída (período P, dia D) fica bloqueado
  no carrinho no MESMO P/D. gerar_escala(..., bloqueio_carrinho=bloqueio) exclui.
- O carrinho NÃO produz mais designacoes_dirigentes.
"""
from datetime import date

from app.engine.calendar_utils import SaidaInstancia, SlotInstancia
from app.engine.sorteio import ContextoSorteio, gerar_escala, gerar_saidas


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


def _slot(dia: int, slot_id: str, periodo: str) -> SlotInstancia:
    return SlotInstancia(
        data=date(2026, 7, dia), slot_id=slot_id, dia_semana="QUARTA",
        requer_dirigente=False, periodo=periodo,
    )


def _saida(dia: int, saida_id: str, periodo: str = "MANHA") -> SaidaInstancia:
    return SaidaInstancia(data=date(2026, 7, dia), saida_id=saida_id, dia_semana="QUARTA", periodo=periodo)


# --- gerar_saidas -----------------------------------------------------------

def test_gerar_saidas_escolhe_um_dirigente_por_saida_respeitando_disponibilidade():
    ctx = _contexto_basico(
        dirigentes_pool={10, 20},
        disponibilidade_saida={"SAIDA_A": {10, 20}},
        ultima_saida={10: "2026-01-01", 20: "2026-06-01"},
    )
    designacoes, bloqueio, _avisos = gerar_saidas([_saida(1, "SAIDA_A", "MANHA")], ctx, "2026-07", date(2026, 7, 1))

    assert len(designacoes) == 1
    assert designacoes[0].saida_id == "SAIDA_A"
    # 10 serviu há mais tempo (jan) -> prioridade sobre 20 (jun)
    assert designacoes[0].dirigente_id == 10
    # mapa de bloqueio por (data_iso, periodo)
    assert bloqueio.get(("2026-07-01", "MANHA")) == {10}


def test_gerar_saidas_fallback_dirigente_sem_disponibilidade_serve_todas():
    # dirigente no pool sem nenhuma linha de disponibilidade = disponível p/ todas
    ctx = _contexto_basico(dirigentes_pool={10}, disponibilidade_saida={})
    designacoes, _bloqueio, _avisos = gerar_saidas([_saida(1, "SAIDA_A", "MANHA")], ctx, "2026-07", date(2026, 7, 1))
    assert len(designacoes) == 1
    assert designacoes[0].dirigente_id == 10


def test_gerar_saidas_nao_repete_dirigente_na_mesma_semana_iso():
    ctx = _contexto_basico(
        dirigentes_pool={10, 20},
        disponibilidade_saida={"SAIDA_A": {10, 20}, "SAIDA_B": {10, 20}},
    )
    instancias = [_saida(1, "SAIDA_A", "MANHA"), _saida(3, "SAIDA_B", "MANHA")]  # mesma semana ISO
    designacoes, _bloqueio, _avisos = gerar_saidas(instancias, ctx, "2026-07", date(2026, 7, 1))
    usados = [d.dirigente_id for d in designacoes]
    assert usados[0] != usados[1]


# --- BLOQUEIO dirigente <-> carrinho ----------------------------------------

def test_dirigente_de_saida_bloqueado_no_carrinho_no_mesmo_periodo_e_dia():
    ctx = _contexto_basico(
        genero_por_pessoa={1: "F", 2: "F"},
        ativos={1, 2},
        disponibilidade_slot={"SLOT_MANHA": {1, 2}},
    )
    bloqueio = {("2026-07-01", "MANHA"): {1}}
    resultado = gerar_escala([_slot(1, "SLOT_MANHA", "MANHA")], ctx, "2026-07", date(2026, 7, 1), bloqueio_carrinho=bloqueio)
    desig = resultado.designacoes[0]
    assert 1 not in (desig.pessoa_id_1, desig.pessoa_id_2)


def test_dirigente_bloqueado_apenas_no_mesmo_periodo_livre_em_periodo_diferente():
    ctx = _contexto_basico(
        genero_por_pessoa={1: "F", 2: "F"},
        ativos={1, 2},
        disponibilidade_slot={"SLOT_TARDE": {1, 2}},
    )
    bloqueio = {("2026-07-01", "MANHA"): {1}}  # bloqueada de manhã; slot é de tarde
    resultado = gerar_escala([_slot(1, "SLOT_TARDE", "TARDE")], ctx, "2026-07", date(2026, 7, 1), bloqueio_carrinho=bloqueio)
    desig = resultado.designacoes[0]
    assert {desig.pessoa_id_1, desig.pessoa_id_2} == {1, 2}


def test_carrinho_sem_bloqueio_escala_normalmente():
    ctx = _contexto_basico(
        genero_por_pessoa={1: "F", 2: "F"},
        ativos={1, 2},
        disponibilidade_slot={"SLOT_MANHA": {1, 2}},
    )
    resultado = gerar_escala([_slot(1, "SLOT_MANHA", "MANHA")], ctx, "2026-07", date(2026, 7, 1))
    desig = resultado.designacoes[0]
    assert {desig.pessoa_id_1, desig.pessoa_id_2} == {1, 2}
