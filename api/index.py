"""Ponto de entrada da Vercel.

A Vercel executa funções serverless: não há processo de longa duração nem
`uvicorn` — a plataforma importa este módulo e fala com `app` pelo protocolo
ASGI. Por isso aqui não há `if __name__ == "__main__"` nem servidor; para rodar
localmente use `python main.py` (desktop) ou `uvicorn api.index:app --reload`.
"""

import sys
from pathlib import Path

# A função roda com a raiz do projeto fora do sys.path; sem isto, `import app`
# falha em produção mesmo funcionando na máquina do desenvolvedor.
RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from app.main_api import create_app  # noqa: E402

app = create_app()
