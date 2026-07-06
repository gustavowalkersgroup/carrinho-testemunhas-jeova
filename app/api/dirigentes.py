from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_conn
from app.models import Dirigente, DirigenteIn, DisponibilidadeUpdateIn
from app.repositories import dirigentes_repo
from app.services import cadastro_service

router = APIRouter(prefix="/api/dirigentes", tags=["dirigentes"])


@router.get("", response_model=list[Dirigente])
def listar_dirigentes(somente_ativos: bool = False, conn=Depends(get_conn)):
    return dirigentes_repo.listar(conn, somente_ativos)


@router.post("", response_model=Dirigente)
def criar_dirigente(dirigente: DirigenteIn, conn=Depends(get_conn)):
    return dirigentes_repo.criar(conn, dirigente)


@router.put("/{dirigente_id}", response_model=Dirigente)
def atualizar_dirigente(dirigente_id: int, dirigente: DirigenteIn, conn=Depends(get_conn)):
    resultado = dirigentes_repo.atualizar(conn, dirigente_id, dirigente)
    if resultado is None:
        raise HTTPException(status_code=404, detail="Dirigente não encontrado")
    return resultado


@router.get("/{dirigente_id}/disponibilidade", response_model=list[str])
def listar_disponibilidade(dirigente_id: int, conn=Depends(get_conn)):
    return dirigentes_repo.listar_slots_do_dirigente(conn, dirigente_id)


@router.put("/{dirigente_id}/disponibilidade")
def definir_disponibilidade(dirigente_id: int, payload: DisponibilidadeUpdateIn, conn=Depends(get_conn)):
    try:
        cadastro_service.definir_disponibilidade_dirigente(conn, dirigente_id, payload.slot_ids)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True}
