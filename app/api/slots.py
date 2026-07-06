from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_conn
from app.models import SlotTipo, SlotTipoIn
from app.repositories import slots_repo

router = APIRouter(prefix="/api/slots", tags=["slots"])


@router.get("", response_model=list[SlotTipo])
def listar_slots(somente_ativos: bool = False, conn=Depends(get_conn)):
    return slots_repo.listar(conn, somente_ativos)


@router.post("", response_model=SlotTipo)
def criar_slot(slot: SlotTipoIn, conn=Depends(get_conn)):
    if slots_repo.obter(conn, slot.slot_id) is not None:
        raise HTTPException(status_code=409, detail="Já existe um slot com esse slot_id")
    return slots_repo.criar(conn, slot)


@router.put("/{slot_id}", response_model=SlotTipo)
def atualizar_slot(slot_id: str, slot: SlotTipoIn, conn=Depends(get_conn)):
    resultado = slots_repo.atualizar(conn, slot_id, slot)
    if resultado is None:
        raise HTTPException(status_code=404, detail="Slot não encontrado")
    return resultado
