"""Geração do PDF + resposta HTTP, num lugar só.

As rotas web e de API montavam a resposta cada uma por conta própria, e as
duas listas de argumentos tinham divergido: a da API passava as saídas de
campo, a da web não — então o PDF baixado pela tela saía sem a seção de
saídas. Com um caminho único isso não volta a acontecer.
"""

from __future__ import annotations

import os

from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from app import config
from app.pdf.pdf_generator import gerar_pdf_escala
from app.services.escala_service import DadosPdf


def _apagar(caminho: str) -> None:
    try:
        os.remove(caminho)
    except OSError:
        # O arquivo é temporário e a instância é descartável; falhar aqui não
        # pode transformar um download bem-sucedido em erro.
        pass


def resposta_pdf(dados: DadosPdf) -> FileResponse:
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

    # No desktop o PDF FICA na pasta de escalas de propósito — o usuário conta
    # com isso para reenviar depois. No modo hospedado o arquivo é temporário
    # e some assim que a resposta termina.
    limpeza = BackgroundTask(_apagar, str(dados.caminho)) if config.MODO_WEB else None

    return FileResponse(
        dados.caminho,
        filename=dados.nome_arquivo or dados.caminho.name,
        media_type="application/pdf",
        background=limpeza,
    )
