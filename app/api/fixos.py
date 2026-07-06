from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_conn
from app.models import Fixo, FixoIn, EncerrarFixoIn
from app.repositories import fixos_repo
from app.services import cadastro_service

router = APIRouter(prefix="/api/fixos", tags=["fixos"])


@router.get("", response_model=list[Fixo])
def listar_fixos(conn=Depends(get_conn)):
    return fixos_repo.listar(conn)


@router.post("", response_model=Fixo)
def criar_fixo(fixo: FixoIn, conn=Depends(get_conn)):
    try:
        return cadastro_service.criar_fixo(conn, fixo)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{fixo_id}/encerrar")
def encerrar_fixo(fixo_id: int, payload: EncerrarFixoIn, conn=Depends(get_conn)):
    if not fixos_repo.encerrar_vigencia(conn, fixo_id, payload.data_fim):
        raise HTTPException(status_code=404, detail="Fixo não encontrado")
    return {"ok": True}
