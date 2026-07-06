import os
import socket
import sys
import threading
import webbrowser

if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

import uvicorn

from app.config import HOST, PORT
from app.main_api import create_app


def _porta_livre(host: str, porta_inicial: int) -> int:
    porta = porta_inicial
    while porta < porta_inicial + 50:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex((host, porta)) != 0:
                return porta
        porta += 1
    return porta_inicial


def _iniciar_servidor(app, host: str, porta: int) -> uvicorn.Server:
    config = uvicorn.Config(app, host=host, port=porta, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    return server


def main() -> None:
    app = create_app()
    porta = _porta_livre(HOST, PORT)
    _iniciar_servidor(app, HOST, porta)
    url = f"http://{HOST}:{porta}/"

    try:
        import webview

        webview.create_window("Escala do Carrinho — Parque das Nações", url, width=1150, height=800)
        webview.start()
    except ImportError:
        webbrowser.open(url)
        input(f"Servidor rodando em {url}\nPressione Enter aqui para encerrar.\n")


if __name__ == "__main__":
    main()
