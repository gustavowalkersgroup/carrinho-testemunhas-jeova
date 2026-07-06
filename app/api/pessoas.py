from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_conn
from app.models import Pessoa, PessoaIn
from app.repositories import pessoas_repo

router = APIRouter(prefix="/api/pessoas", tags=["pessoas"])


@router.get("", response_model=list[Pessoa])
def listar_pessoas(somente_ativos: bool = False, conn=Depends(get_conn)):
    return pessoas_repo.listar(conn, somente_ativos)


@router.get("/{pessoa_id}", response_model=Pessoa)
def obter_pessoa(pessoa_id: int, conn=Depends(get_conn)):
    pessoa = pessoas_repo.obter(conn, pessoa_id)
    if pessoa is None:
        raise HTTPException(status_code=404, detail="Pessoa não encontrada")
    return pessoa


@router.post("", response_model=Pessoa)
def criar_pessoa(pessoa: PessoaIn, conn=Depends(get_conn)):
    return pessoas_repo.criar(conn, pessoa)


@router.put("/{pessoa_id}", response_model=Pessoa)
def atualizar_pessoa(pessoa_id: int, pessoa: PessoaIn, conn=Depends(get_conn)):
    resultado = pessoas_repo.atualizar(conn, pessoa_id, pessoa)
    if resultado is None:
        raise HTTPException(status_code=404, detail="Pessoa não encontrada")
    return resultado


@router.delete("/{pessoa_id}")
def inativar_pessoa(pessoa_id: int, conn=Depends(get_conn)):
    if not pessoas_repo.inativar(conn, pessoa_id):
        raise HTTPException(status_code=404, detail="Pessoa não encontrada")
    return {"ok": True}
