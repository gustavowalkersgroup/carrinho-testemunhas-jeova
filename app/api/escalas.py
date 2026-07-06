from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from app.api.deps import get_conn
from app.models import DesignacaoDirigenteUpdateIn, DesignacaoUpdateIn, EscalaMensal
from app.pdf.pdf_generator import gerar_pdf_escala
from app.services import escala_service

router = APIRouter(prefix="/api/escalas", tags=["escalas"])


@router.post("/{ano}/{mes}/gerar", response_model=EscalaMensal)
def gerar_rascunho(ano: int, mes: int, conn=Depends(get_conn)):
    return escala_service.gerar_rascunho(conn, ano, mes, date.today())


@router.get("/{mes_referencia}", response_model=EscalaMensal)
def obter_escala(mes_referencia: str, conn=Depends(get_conn)):
    return escala_service.obter_escala(conn, mes_referencia)


@router.put("/designacao/{designacao_id}")
def editar_designacao(designacao_id: int, payload: DesignacaoUpdateIn, conn=Depends(get_conn)):
    if not escala_service.editar_designacao(conn, designacao_id, payload.pessoa_id_1, payload.pessoa_id_2):
        raise HTTPException(status_code=404, detail="Designação não encontrada (ou já fechada)")
    return {"ok": True}


@router.put("/designacao-dirigente/{designacao_id}")
def editar_designacao_dirigente(designacao_id: int, payload: DesignacaoDirigenteUpdateIn, conn=Depends(get_conn)):
    if not escala_service.editar_designacao_dirigente(conn, designacao_id, payload.dirigente_id):
        raise HTTPException(status_code=404, detail="Designação não encontrada (ou já fechada)")
    return {"ok": True}


@router.post("/{mes_referencia}/fechar")
def fechar_mes(mes_referencia: str, conn=Depends(get_conn)):
    escala_service.fechar_mes(conn, mes_referencia)
    return {"ok": True}


@router.get("/{mes_referencia}/pdf")
def exportar_pdf(mes_referencia: str, conn=Depends(get_conn)):
    ano, mes = (int(x) for x in mes_referencia.split("-"))

    # agregação centralizada no service (BUG #9): montar_dados_pdf devolve os dados
    # já prontos + o caminho de saída, em vez de reimplementar tudo aqui.
    dados = escala_service.montar_dados_pdf(conn, ano, mes)
    gerar_pdf_escala(
        dados.mes_referencia,
        dados.designacoes,
        dados.designacoes_dirigentes,
        dados.slots,
        dados.bloqueios,
        dados.pessoas_por_id,
        dados.dirigentes_por_id,
        dados.caminho,
        designacoes_saidas=dados.designacoes_saidas,
        saidas_por_id=dados.saidas_por_id,
    )
    return FileResponse(dados.caminho, filename=dados.caminho.name, media_type="application/pdf")
