"""
Only keep this manager for testing purposes. Since it uses separated conn pool
"""

from collections.abc import Callable, Generator, Iterator
from functools import wraps

from sqlalchemy import Connection, create_engine
from sqlalchemy.orm import Session, sessionmaker

from core.conf import get_app_settings
from core.db.sa.engine import Base

from ..types_legacy import IDBSessionManager


class DbSessionManagerSync(IDBSessionManager):
    def __init__(self, url: str | None = None):
        settings = get_app_settings()
        url = url or str(settings.SQLALCHEMY_DATABASE_URI)
        self._engine = create_engine(url, echo=settings.DATABASE_LOG_SQL)
        self._sessionmaker = sessionmaker(
            # autocommit=False,
            bind=self._engine,
        )

    def close(self):
        if self._engine is None:
            return

        self._engine.dispose()
        self._engine = None
        self._sessionmaker = None

    def get_engine(self):
        return self._engine

    def connect(self) -> Iterator[Connection]:
        if self._engine is None:
            raise Exception('DatabaseSessionManager is not initialized')

        with self._engine.begin() as connection:
            try:
                yield connection
            except Exception:
                connection.rollback()
                raise

    def get_session(self) -> Session:
        return self._sessionmaker()  # type: ignore

    def get_session_generator(self) -> Iterator[sessionmaker]:
        """
        FastAPI applications for dependency injection
        Here's a typical usage example:
        @app.get("/users")
        def get_users(db: Session = Depends(get_db)):
            users = db.exec(select(User)).all()
            return users
        """
        session = self.get_session()
        try:
            yield session
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()


class MainDBSessionManager:
    _instance: 'DbSessionManagerSync | None' = None

    # def __new__(cls):
    #     """Ensure singleton pattern."""
    #     if cls._instance is None:
    #         cls._instance = super().__new__(cls)
    #     return cls._instance

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = DbSessionManagerSync(*args, **kwargs)
        return cls._instance

    def __init__(self, value):
        # __init__ will be called every time, even for existing instances.
        # Ensure initialization logic only runs once or handles re-initialization carefully.
        if not hasattr(self, '_initialized'):  # Prevent re-initialization
            self._initialized = True
            # Initialization logic here, if any

    @classmethod
    def get_instance(cls) -> 'DbSessionManagerSync':
        if cls._instance is None:
            cls._instance = DbSessionManagerSync()
        return cls._instance


def db_session_sync(func: Callable) -> Callable:
    @wraps(func)
    def wrapper(*args, **kwargs):
        with MainDBSessionManager.get_instance().get_session() as session:
            try:
                result = func(*args, session=session, **kwargs)
                # session.commit()
                return result
            except Exception:
                session.rollback()
                raise
            finally:
                session.close()

    return wrapper


def get_db_generator() -> Generator[Session, None, None]:
    """
    FastAPI applications for dependency injection
    Here's a typical usage example:
    @app.get("/users")
    def get_users(db: Session = Depends(get_db)):
        users = MainDBSessionManagerSync.get_instance().exec(select(User)).all()
        return users
    """
    with MainDBSessionManager.get_instance().get_session() as session:
        yield session


def create_all_tables_sync():
    # Create all tables in the engine
    # import app.core.keycloak.db.kc_models as b  # noqa: F401
    # import app.core.web3.crypto.models as a  # noqa: F401
    # import app.core.web3.crypto.models_kyc as kyc  # noqa: F401
    # import app.core.web3.crypto.models_risk_matrix as rm  # noqa: F401
    # import app.core.web3.crypto.travel_rule as tr  # noqa: F401

    Base.metadata.create_all(MainDBSessionManager.get_instance()._engine)  # type: ignore
