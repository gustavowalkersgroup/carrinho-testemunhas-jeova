from app.models import Pessoa, SlotTipo


def validar_pool_minimo(pessoas: list[Pessoa]) -> list[str]:
    """Retorna chaves de tradução (app/i18n.py), não texto final."""
    avisos = []
    ativos = [p for p in pessoas if p.ativo]
    homens = [p for p in ativos if p.genero == "M"]
    mulheres = [p for p in ativos if p.genero == "F"]
    if len(homens) < 2:
        avisos.append("aviso.pool_minimo_homens")
    if len(mulheres) < 2:
        avisos.append("aviso.pool_minimo_mulheres")
    return avisos


def validar_template_slots(slots: list[SlotTipo]) -> list[str]:
    """Retorna chaves de tradução (app/i18n.py), não texto final."""
    avisos = []
    if not slots:
        avisos.append("aviso.sem_slots_vigentes")
    return avisos
