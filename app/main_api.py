from urllib.parse import urlparse

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles

from app.api import bloqueios, dirigentes, disponibilidades, escalas, fixos, pessoas, saidas, slots
from app.config import STATIC_DIR
from app.db.migrations import run_migrations
from app.web.routes import router as web_router

# Metodos que alteram estado precisam de checagem CSRF.
_METODOS_INSEGUROS = {"POST", "PUT", "PATCH", "DELETE"}
# Hosts confiaveis: o app roda local em 127.0.0.1/localhost (qualquer porta).
_HOSTS_PERMITIDOS = {"127.0.0.1", "localhost"}


def create_app() -> FastAPI:
    run_migrations()

    app = FastAPI(title="Gerador de Escala do Carrinho")

    app.include_router(pessoas.router)
    app.include_router(slots.router)
    app.include_router(disponibilidades.router)
    app.include_router(fixos.router)
    app.include_router(dirigentes.router)
    app.include_router(saidas.router)
    app.include_router(bloqueios.router)
    app.include_router(escalas.router)
    app.include_router(web_router)

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.middleware("http")
    async def verificar_origem_csrf(request: Request, call_next):
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
                if host not in _HOSTS_PERMITIDOS:
                    return PlainTextResponse(
                        "Origem nao permitida (possivel CSRF).", status_code=403
                    )
        return await call_next(request)

    return app
