from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_conn
from app.models import DesignacaoSaidaUpdateIn, SaidaCampoTemplate, SaidaCampoTemplateIn
from app.repositories import saida_repo
from app.services import escala_service

router = APIRouter(prefix="/api/saidas", tags=["saidas"])


@router.get("", response_model=list[SaidaCampoTemplate])
def listar_saidas(somente_ativos: bool = False, conn=Depends(get_conn)):
    return saida_repo.listar(conn, somente_ativos)


@router.post("", response_model=SaidaCampoTemplate)
def criar_saida(saida: SaidaCampoTemplateIn, conn=Depends(get_conn)):
    if saida_repo.obter(conn, saida.saida_id) is not None:
        raise HTTPException(status_code=409, detail="Já existe uma saída com esse saida_id")
    return saida_repo.criar(conn, saida)


@router.put("/{saida_id}", response_model=SaidaCampoTemplate)
def atualizar_saida(saida_id: str, saida: SaidaCampoTemplateIn, conn=Depends(get_conn)):
    resultado = saida_repo.atualizar(conn, saida_id, saida)
    if resultado is None:
        raise HTTPException(status_code=404, detail="Saída não encontrada")
    return resultado


@router.get("/dirigentes/{pessoa_id}/disponibilidade", response_model=list[str])
def listar_disponibilidade(pessoa_id: int, conn=Depends(get_conn)):
    return saida_repo.listar_saidas_do_dirigente(conn, pessoa_id)


@router.put("/dirigentes/{pessoa_id}/disponibilidade")
def definir_disponibilidade(pessoa_id: int, saida_ids: list[str], conn=Depends(get_conn)):
    try:
        saida_repo.definir_disponibilidade_do_dirigente(conn, pessoa_id, saida_ids)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True}


@router.put("/designacao/{designacao_id}")
def editar_designacao_saida(designacao_id: int, payload: DesignacaoSaidaUpdateIn, conn=Depends(get_conn)):
    if not escala_service.editar_designacao_saida(conn, designacao_id, payload.dirigente_id):
        raise HTTPException(status_code=404, detail="Designação de saída não encontrada (ou já fechada)")
    return {"ok": True}
