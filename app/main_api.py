import logging
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app import config
from app.api import bloqueios, dirigentes, disponibilidades, escalas, fixos, pessoas, saidas, slots
from app.auth import service as auth_service
from app.auth.deps import (
    PrecisaEntrar,
    PrecisaEscolherCongregacao,
    SemPermissao,
    exigir_acesso,
)
from app.config import STATIC_DIR
from app.db.connection import get_connection
from app.db.migrations import run_migrations
from app.web.admin_routes import router as admin_router
from app.web.auth_routes import router as auth_router
from app.web.render import render
from app.web.routes import router as web_router

logger = logging.getLogger("escala")

# Metodos que alteram estado precisam de checagem CSRF.
_METODOS_INSEGUROS = {"POST", "PUT", "PATCH", "DELETE"}
# No desktop o app roda em 127.0.0.1/localhost; no modo WEB, o host válido é o
# próprio domínio que atendeu o request (comparação same-origin).
_HOSTS_LOCAIS = {"127.0.0.1", "localhost"}

# A migração roda uma vez por processo. Em serverless cada instância nova
# repete a checagem, que é uma consulta só quando o schema já está em dia.
_migracao_feita = False


def _garantir_migracao() -> None:
    """No modo WEB roda uma vez por processo; no desktop, sempre.

    O cache é só do modo WEB de propósito: no SQLite a migração custa
    milissegundos e o caminho do banco pode mudar entre chamadas (é o que os
    testes fazem ao apontar config.DB_PATH para um arquivo temporário), então
    memorizar ali criaria um app ligado a um banco que não existe mais."""
    global _migracao_feita
    if config.MODO_LOCAL:
        run_migrations()
        return

    if _migracao_feita:
        return
    run_migrations()
    with get_connection() as conn:
        auth_service.garantir_super_admins(conn)
    _migracao_feita = True


def _hosts_permitidos(request: Request) -> set[str]:
    permitidos = set(_HOSTS_LOCAIS)
    cabecalho_host = (request.headers.get("host") or "").split(":")[0]
    if cabecalho_host:
        permitidos.add(cabecalho_host)
    if config.APP_BASE_URL:
        host_configurado = urlparse(config.APP_BASE_URL).hostname
        if host_configurado:
            permitidos.add(host_configurado)
    return permitidos


def _quer_json(request: Request) -> bool:
    if request.url.path.startswith("/api"):
        return True
    return "application/json" in (request.headers.get("accept") or "")


def create_app() -> FastAPI:
    if config.MODO_LOCAL:
        # No desktop a migração pode rodar já: é um SQLite local, instantâneo.
        # No modo WEB fica para o primeiro request, para que um banco fora do ar
        # não impeça o módulo de carregar.
        _garantir_migracao()

    app = FastAPI(title="Escala do Carrinho")

    if config.MODO_WEB and not config.SECRET_KEY:
        logger.warning(
            "SECRET_KEY não definida: as sessões cairão a cada instância nova. "
            "Defina SECRET_KEY nas variáveis de ambiente."
        )

    # Rotas públicas (entrar, solicitar acesso): sem exigência de sessão.
    app.include_router(auth_router)

    # Rotas de domínio: uma única guarda para todas. Ler exige pertencer à
    # congregação; escrever exige perfil de edição (ver auth/deps.exigir_acesso).
    protegido = [Depends(exigir_acesso)]
    app.include_router(pessoas.router, dependencies=protegido)
    app.include_router(slots.router, dependencies=protegido)
    app.include_router(disponibilidades.router, dependencies=protegido)
    app.include_router(fixos.router, dependencies=protegido)
    app.include_router(dirigentes.router, dependencies=protegido)
    app.include_router(saidas.router, dependencies=protegido)
    app.include_router(bloqueios.router, dependencies=protegido)
    app.include_router(escalas.router, dependencies=protegido)

    # O painel tem regras próprias por rota (admin de congregação x super-admin).
    app.include_router(admin_router)

    app.include_router(web_router, dependencies=protegido)

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.exception_handler(PrecisaEntrar)
    async def _sem_sessao(request: Request, exc: PrecisaEntrar):
        if _quer_json(request):
            return JSONResponse({"detail": "Autenticação necessária."}, status_code=401)
        return RedirectResponse(url="/entrar", status_code=303)

    # Os handlers abaixo renderizam SEM conexão de propósito: quando a exceção
    # sobe de uma dependência, a conexão do request já foi fechada no unwind.
    # Sem banco, o idioma vem do cookie e o nome da congregação, da sessão.

    @app.exception_handler(PrecisaEscolherCongregacao)
    async def _sem_congregacao(request: Request, exc: PrecisaEscolherCongregacao):
        if _quer_json(request):
            return JSONResponse({"detail": "Nenhuma congregação liberada."}, status_code=403)
        return render("sem_congregacao.html", request, None, status_code=403)

    @app.exception_handler(SemPermissao)
    async def _sem_permissao(request: Request, exc: SemPermissao):
        if _quer_json(request):
            return JSONResponse({"detail": exc.detalhe}, status_code=403)
        return render("sem_permissao.html", request, None, status_code=403, detalhe=exc.detalhe)

    @app.middleware("http")
    async def preparar_e_verificar_origem(request: Request, call_next):
        if config.MODO_WEB:
            _garantir_migracao()

        # Protecao CSRF na estrategia "verify origin when present":
        # navegadores modernos SEMPRE enviam Origin num POST cross-site,
        # entao basta rejeitar quando o Origin/Referer aponta para outro host.
        # Requests same-origin de <form> e do TestClient nao mandam Origin,
        # portanto a checagem nao quebra o app nem os testes.
        if request.method in _METODOS_INSEGUROS:
            origem = request.headers.get("origin") or request.headers.get("referer")
            # So checamos quando ha Origin/Referer; ausencia -> permite.
            if origem:
                host = urlparse(origem).hostname
                if host not in _hosts_permitidos(request):
                    return PlainTextResponse(
                        "Origem nao permitida (possivel CSRF).", status_code=403
                    )
        return await call_next(request)

    return app
