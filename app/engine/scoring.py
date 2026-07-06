from datetime import date
from typing import Iterable


def chave_prioridade(entidade_id: int, ultima_designacao: dict[int, str], total_designacoes: dict[int, int], hoje: date):
    """Chave de ordenação ascendente: quem está há mais tempo sem servir vem primeiro
    (nunca serviu = prioridade máxima); empate é desempatado por quem serviu menos vezes
    no total. Usa o histórico completo (sem janela), conforme decidido com o usuário.
    """
    ultima_str = ultima_designacao.get(entidade_id)
    if ultima_str is None:
        primeira_chave = float("-inf")
    else:
        # clamp em 0: se ultima_str > hoje (mês fechado fora de ordem ou relógio
        # errado), o delta seria negativo e inverteria a prioridade (quem serviu
        # "no futuro" pareceria estar há mais tempo sem servir). Tratamos como
        # servido hoje (0 dias) nesse caso.
        dias_sem_servir = max(0, (hoje - date.fromisoformat(ultima_str)).days)
        primeira_chave = -dias_sem_servir

    total = total_designacoes.get(entidade_id, 0)
    return (primeira_chave, total)


def ordenar_por_prioridade(entidades: Iterable[int], ultima_designacao: dict[int, str], total_designacoes: dict[int, int], hoje: date) -> list[int]:
    return sorted(entidades, key=lambda e: chave_prioridade(e, ultima_designacao, total_designacoes, hoje))
