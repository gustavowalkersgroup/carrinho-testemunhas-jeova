from app.db.connection import get_connection


def get_conn():
    with get_connection() as conn:
        yield conn
