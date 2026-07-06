from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_conn
from app.models import Bloqueio, BloqueioIn
from app.repositories import bloqueios_repo

router = APIRouter(prefix="/api/bloqueios", tags=["bloqueios"])


@router.get("", response_model=list[Bloqueio])
def listar_bloqueios(conn=Depends(get_conn)):
    return bloqueios_repo.listar(conn)


@router.post("", response_model=Bloqueio)
def criar_bloqueio(bloqueio: BloqueioIn, conn=Depends(get_conn)):
    return bloqueios_repo.criar(conn, bloqueio)


@router.delete("/{bloqueio_id}")
def remover_bloqueio(bloqueio_id: int, conn=Depends(get_conn)):
    if not bloqueios_repo.remover(conn, bloqueio_id):
        raise HTTPException(status_code=404, detail="Bloqueio não encontrado")
    return {"ok": True}
