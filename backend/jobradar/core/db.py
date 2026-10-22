"""Accès base de données : un moteur SQLAlchemy synchrone (PostgreSQL en cible, SQLite pour les tests rapides)."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker


class Database:
    def __init__(self, url: str, *, echo: bool = False) -> None:
        self.url = url
        is_sqlite = url.startswith("sqlite")
        connect_args = {"check_same_thread": False, "timeout": 30} if is_sqlite else {}
        self.engine: Engine = create_engine(
            url, echo=echo, pool_pre_ping=True, connect_args=connect_args, future=True
        )
        if is_sqlite:

            @event.listens_for(self.engine, "connect")
            def _sqlite_pragmas(dbapi_conn, _record):  # pragma: no cover - dépend du backend
                dbapi_conn.isolation_level = None  # contrôle transactionnel par SQLAlchemy (SAVEPOINT fiables)
                cur = dbapi_conn.cursor()
                cur.execute("PRAGMA foreign_keys=ON")
                cur.execute("PRAGMA journal_mode=WAL")
                cur.execute("PRAGMA busy_timeout=30000")
                cur.close()

            @event.listens_for(self.engine, "begin")
            def _sqlite_begin(conn):  # pragma: no cover
                conn.exec_driver_sql("BEGIN")

        self.session_factory = sessionmaker(self.engine, expire_on_commit=False, future=True)
        # SQLite (tests uniquement) n'admet qu'un écrivain et échoue aussitôt (« database is locked », sans attendre
        # busy_timeout) quand une transaction qui a déjà lu tente d'écrire après le commit d'une autre. Les sessions
        # des services (collecte, veille) sont donc sérialisées dans le processus. PostgreSQL : aucun verrou.
        self._serial = threading.RLock() if is_sqlite else None

    @contextmanager
    def session(self) -> Iterator[Session]:
        """Session avec commit en sortie normale et rollback sur exception."""
        if self._serial is not None:
            self._serial.acquire()
        s = self.session_factory()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()
            if self._serial is not None:
                self._serial.release()

    def dispose(self) -> None:
        self.engine.dispose()
