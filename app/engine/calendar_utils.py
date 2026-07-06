from calendar import monthrange
from dataclasses import dataclass
from datetime import date
from typing import Iterable

from app.config import PYTHON_WEEKDAY_TO_DIA_SEMANA


def _periodo_str(periodo) -> str:
    """Aceita enum Periodo ou string; devolve 'MANHA'/'TARDE'."""
    return getattr(periodo, "value", periodo)


@dataclass(frozen=True)
class SlotInstancia:
    data: date
    slot_id: str
    dia_semana: str
    requer_dirigente: bool
    periodo: str = ""  # 'MANHA'/'TARDE' — usado pelo bloqueio dirigente↔carrinho


@dataclass(frozen=True)
class SaidaInstancia:
    data: date
    saida_id: str
    dia_semana: str
    periodo: str  # 'MANHA'/'TARDE'


def gerar_instancias_saida(ano: int, mes: int, saidas_vigentes: Iterable, bloqueios: Iterable) -> list[SaidaInstancia]:
    """Cruza os dias do mês com o template semanal de saídas de campo vigente,
    pulando datas bloqueadas. Mesma lógica de gerar_instancias, mas para saídas."""
    _, dias_no_mes = monthrange(ano, mes)

    saidas_por_dia: dict[str, list] = {}
    for s in saidas_vigentes:
        saidas_por_dia.setdefault(s.dia_semana, []).append(s)
    for lista in saidas_por_dia.values():
        lista.sort(key=lambda s: s.ordem)

    bloqueios_lista = list(bloqueios)

    instancias: list[SaidaInstancia] = []
    for dia in range(1, dias_no_mes + 1):
        data_atual = date(ano, mes, dia)
        if _data_bloqueada(data_atual, bloqueios_lista):
            continue
        dia_semana = PYTHON_WEEKDAY_TO_DIA_SEMANA[data_atual.weekday()]
        for s in saidas_por_dia.get(dia_semana, []):
            instancias.append(
                SaidaInstancia(
                    data=data_atual,
                    saida_id=s.saida_id,
                    dia_semana=dia_semana,
                    periodo=_periodo_str(getattr(s, "periodo", "")),
                )
            )
    instancias.sort(key=lambda i: i.data)
    return instancias


def gerar_instancias(ano: int, mes: int, slots_vigentes: Iterable, bloqueios: Iterable) -> list[SlotInstancia]:
    """Cruza os dias do mês com o template semanal vigente, pulando datas bloqueadas.

    `slots_vigentes` e `bloqueios` aceitam qualquer objeto com os atributos usados
    abaixo (SlotTipo/Bloqueio do models.py, por exemplo).
    """
    _, dias_no_mes = monthrange(ano, mes)

    slots_por_dia_semana: dict[str, list] = {}
    for slot in slots_vigentes:
        slots_por_dia_semana.setdefault(slot.dia_semana, []).append(slot)
    for lista in slots_por_dia_semana.values():
        lista.sort(key=lambda s: s.ordem)

    bloqueios_lista = list(bloqueios)

    instancias: list[SlotInstancia] = []
    for dia in range(1, dias_no_mes + 1):
        data_atual = date(ano, mes, dia)
        if _data_bloqueada(data_atual, bloqueios_lista):
            continue
        dia_semana = PYTHON_WEEKDAY_TO_DIA_SEMANA[data_atual.weekday()]
        for slot in slots_por_dia_semana.get(dia_semana, []):
            instancias.append(
                SlotInstancia(
                    data=data_atual,
                    slot_id=slot.slot_id,
                    dia_semana=dia_semana,
                    requer_dirigente=slot.requer_dirigente,
                    periodo=_periodo_str(getattr(slot, "periodo", "")),
                )
            )

    # sort() é estável: preserva, dentro do mesmo dia, a ordem por `ordem` já
    # aplicada acima — ordenar por slot_id aqui destruiria esse agrupamento.
    instancias.sort(key=lambda i: i.data)
    return instancias


def _data_bloqueada(data_atual: date, bloqueios: list) -> bool:
    return any(b.data_inicio <= data_atual <= b.data_fim for b in bloqueios)
