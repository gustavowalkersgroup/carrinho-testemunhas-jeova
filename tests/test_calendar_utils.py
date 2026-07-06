from dataclasses import dataclass
from datetime import date
from typing import Optional

from app.engine.calendar_utils import gerar_instancias


@dataclass
class FakeSlot:
    slot_id: str
    dia_semana: str
    ordem: int
    requer_dirigente: bool = False


@dataclass
class FakeBloqueio:
    data_inicio: date
    data_fim: date


def _slots_basicos():
    return [
        FakeSlot("SEG_TARDE", "SEGUNDA", 1, requer_dirigente=True),
        FakeSlot("QUA_MANHA", "QUARTA", 3),
        FakeSlot("QUA_COND", "QUARTA", 4),
        FakeSlot("QUA_TARDE", "QUARTA", 5, requer_dirigente=True),
    ]


def test_gera_uma_instancia_por_slot_por_ocorrencia_do_dia_da_semana():
    instancias = gerar_instancias(2026, 7, _slots_basicos(), [])
    segundas = [i for i in instancias if i.dia_semana == "SEGUNDA"]
    quartas = [i for i in instancias if i.dia_semana == "QUARTA"]

    # julho/2026 tem 5 segundas (06,13,20,27) -> na verdade 4, e 4 quartas (01,08,15,22,29) -> 5
    assert len(segundas) == 4
    assert len(quartas) == 5 * 3  # 3 slots por quarta-feira


def test_quarta_feira_gera_os_tres_slots_na_ordem_correta():
    instancias = gerar_instancias(2026, 7, _slots_basicos(), [])
    primeira_quarta = [i for i in instancias if i.data == date(2026, 7, 1)]
    assert [i.slot_id for i in primeira_quarta] == ["QUA_MANHA", "QUA_COND", "QUA_TARDE"]


def test_requer_dirigente_propagado_da_definicao_do_slot():
    instancias = gerar_instancias(2026, 7, _slots_basicos(), [])
    seg = next(i for i in instancias if i.slot_id == "SEG_TARDE")
    qua_manha = next(i for i in instancias if i.slot_id == "QUA_MANHA")
    assert seg.requer_dirigente is True
    assert qua_manha.requer_dirigente is False


def test_datas_bloqueadas_sao_excluidas():
    bloqueio = FakeBloqueio(date(2026, 7, 8), date(2026, 7, 8))
    instancias = gerar_instancias(2026, 7, _slots_basicos(), [bloqueio])
    assert all(i.data != date(2026, 7, 8) for i in instancias)


def test_bloqueio_de_intervalo_exclui_varios_dias():
    bloqueio = FakeBloqueio(date(2026, 7, 12), date(2026, 7, 14))
    instancias = gerar_instancias(2026, 7, _slots_basicos(), [bloqueio])
    datas = {i.data for i in instancias}
    assert date(2026, 7, 12) not in datas
    assert date(2026, 7, 13) not in datas
    assert date(2026, 7, 14) not in datas
    assert date(2026, 7, 15) in datas
