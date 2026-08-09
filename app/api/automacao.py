"""API para integrações externas (n8n, scripts), autenticada por chave fixa
(`AUTOMACAO_API_KEY`) em vez de sessão de navegador.

Por que uma API separada de `/api/pessoas` etc.: aquelas exigem sessão
(cookie de login por código de e-mail), que não faz sentido para uma
automação. Aqui a autorização é o header `X-Api-Key` (ver
`app.auth.deps.exigir_api_key`), e cada rota recebe `congregacao_id`
explicitamente no corpo — sem sessão não há congregação "atual" para inferir.
"""

from __future__ import annotations

import logging
import traceback
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request

from app.auth import repo as auth_repo
from app.auth.deps import exigir_api_key
from app.db.connection import get_connection
from app.services import importacao_historico

logger = logging.getLogger("escala.automacao")

router = APIRouter(prefix="/api/automacao", tags=["automacao"], dependencies=[Depends(exigir_api_key)])


@router.get("/congregacoes")
def listar_congregacoes():
    """Ajuda a achar o `congregacao_id` a passar nas outras rotas."""
    with get_connection() as conn:
        congregacoes = auth_repo.listar_congregacoes(conn)
    return [c.model_dump() for c in congregacoes]


# ROTA TEMPORÁRIA: existe só para popular a primeira congregação a partir de
# um histórico de designações. Remover depois de usada uma vez (ver
# app/services/importacao_historico.py para o porquê de não haver dado de
# nenhuma pessoa real no código).
@router.post("/importar-historico")
async def importar_historico_route(request: Request):
    corpo = await request.json()
    congregacao_id = corpo.get("congregacao_id")
    if not congregacao_id:
        raise HTTPException(400, "Informe `congregacao_id` no corpo da requisição (veja GET /api/automacao/congregacoes).")

    vigencia = corpo.get("vigencia_inicio_fixos")
    if vigencia:
        vigencia = date.fromisoformat(vigencia)

    try:
        with get_connection(congregacao_id=congregacao_id) as conn:
            relatorio = importacao_historico.importar_historico(
                conn,
                historico=corpo["historico"],
                genero=corpo["genero"],
                genero_incerto=corpo.get("genero_incerto"),
                dirigentes_pool=corpo.get("dirigentes_pool"),
                fixo_fracao_minima=corpo.get("fixo_fracao_minima", importacao_historico.FIXO_FRACAO_MINIMA_PADRAO),
                fixo_meses_minimos=corpo.get("fixo_meses_minimos", importacao_historico.FIXO_MESES_MINIMOS_PADRAO),
                vigencia_inicio_fixos=vigencia,
                mes_limite_inativos=corpo.get("mes_limite_inativos"),
            )
    except Exception as e:
        # Endpoint temporário e só acessível com a API key: expor o traceback
        # aqui vale mais do que economizar uma rodada de "olha o log da Vercel".
        logger.exception("falha ao importar histórico")
        raise HTTPException(500, f"{type(e).__name__}: {e}\n{traceback.format_exc()}") from e

    return {"relatorio_texto": importacao_historico.formatar_relatorio(relatorio), "relatorio": relatorio}
