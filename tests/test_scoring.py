from datetime import date

from app.engine.scoring import chave_prioridade, ordenar_por_prioridade


def test_quem_nunca_serviu_tem_prioridade_maxima():
    hoje = date(2026, 7, 1)
    ultima = {1: "2026-06-01"}
    total = {1: 5}
    chave_nunca_serviu = chave_prioridade(2, ultima, total, hoje)
    chave_ja_serviu = chave_prioridade(1, ultima, total, hoje)
    assert chave_nunca_serviu < chave_ja_serviu


def test_quem_serviu_ha_mais_tempo_vem_primeiro():
    hoje = date(2026, 7, 1)
    ultima = {1: "2026-01-01", 2: "2026-06-01"}
    total = {1: 3, 2: 3}
    ordenados = ordenar_por_prioridade([1, 2], ultima, total, hoje)
    assert ordenados == [1, 2]


def test_desempate_por_menor_total_de_designacoes():
    hoje = date(2026, 7, 1)
    ultima = {1: "2026-06-01", 2: "2026-06-01"}
    total = {1: 10, 2: 2}
    ordenados = ordenar_por_prioridade([1, 2], ultima, total, hoje)
    assert ordenados == [2, 1]
