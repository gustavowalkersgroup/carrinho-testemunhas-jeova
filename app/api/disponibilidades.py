from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_conn
from app.models import DisponibilidadeUpdateIn
from app.repositories import disponibilidades_repo
from app.services import cadastro_service

router = APIRouter(prefix="/api/disponibilidades", tags=["disponibilidades"])


@router.get("/pessoa/{pessoa_id}", response_model=list[str])
def listar_da_pessoa(pessoa_id: int, conn=Depends(get_conn)):
    return disponibilidades_repo.listar_slots_da_pessoa(conn, pessoa_id)


@router.put("/pessoa/{pessoa_id}")
def definir_da_pessoa(pessoa_id: int, payload: DisponibilidadeUpdateIn, conn=Depends(get_conn)):
    try:
        cadastro_service.definir_disponibilidade_pessoa(conn, pessoa_id, payload.slot_ids)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True}
