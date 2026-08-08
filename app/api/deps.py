"""Mantido por compatibilidade: `get_conn` agora mora em `app/auth/deps.py`,
onde a conexão já nasce apontada para a congregação da sessão."""

from app.auth.deps import get_conn

__all__ = ["get_conn"]
