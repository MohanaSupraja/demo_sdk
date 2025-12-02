import logging
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)


class DatabaseInstrumentor:
    """
    Production-grade instrumentor for database libraries.

    Supports:
        - SQLAlchemy
        - Psycopg2
        - PyMySQL
        - Redis
        - PyMongo

    Features:
        - Safe fallback (never breaks user app)
        - Idempotent instrumentation
        - Optional engine-based SQLAlchemy instrumentation
    """

    _INSTRUMENTOR_MAP: Dict[str, tuple] = {
        "sqlalchemy": (
            "opentelemetry.instrumentation.sqlalchemy",
            "SQLAlchemyInstrumentor",
        ),
        "psycopg2": (
            "opentelemetry.instrumentation.psycopg2",
            "Psycopg2Instrumentor",
        ),
        "pymysql": (
            "opentelemetry.instrumentation.pymysql",
            "PyMySQLInstrumentor",
        ),
        "redis": (
            "opentelemetry.instrumentation.redis",
            "RedisInstrumentor",
        ),
        "pymongo": (
            "opentelemetry.instrumentation.pymongo",
            "MongoDBInstrumentor",
        ),
    }

    def __init__(self):
        self._status: Dict[str, str] = {}  # lib -> "instrumented" / "uninstrumented"

    # ----------------------------------------------------------------------
    def instrument(self, libraries: List[str], sqlalchemy_engine: Optional[Any] = None) -> Dict[str, bool]:
        """
        Instrument database libraries.

        :param libraries: list of library names
        :param sqlalchemy_engine: optional SQLAlchemy engine for SQLAlchemy instrumentation
        """
        results = {}

        for lib in libraries:
            lib = lib.lower()

            # Already instrumented
            if self._status.get(lib) == "instrumented":
                results[lib] = True
                continue

            # Unsupported library
            if lib not in self._INSTRUMENTOR_MAP:
                logger.debug("No database instrumentor found for %s", lib)
                results[lib] = False
                continue

            module_path, class_name = self._INSTRUMENTOR_MAP[lib]

            try:
                mod = __import__(module_path, fromlist=[class_name])
                Instrumentor = getattr(mod, class_name)
            except Exception as e:
                logger.debug("Failed to import instrumentor for %s: %s", lib, e, exc_info=True)
                results[lib] = False
                continue

            inst = Instrumentor()

            try:
                # Special handling for SQLAlchemy
                if lib == "sqlalchemy" and sqlalchemy_engine is not None:
                    inst.instrument(engine=sqlalchemy_engine)
                else:
                    inst.instrument()

                self._status[lib] = "instrumented"
                logger.info("Instrumented database library: %s", lib)
                results[lib] = True

            except Exception as e:
                logger.debug("Instrumentation failed for %s: %s", lib, e, exc_info=True)
                results[lib] = False

        return results

    # ----------------------------------------------------------------------
    def uninstrument(self, lib: str) -> bool:
        """Undo instrumentation for a single library."""
        lib = lib.lower()

        if lib not in self._INSTRUMENTOR_MAP:
            return False

        module_path, class_name = self._INSTRUMENTOR_MAP[lib]

        try:
            mod = __import__(module_path, fromlist=[class_name])
            Instrumentor = getattr(mod, class_name)
            inst = Instrumentor()
        except Exception:
            return False

        try:
            if hasattr(inst, "uninstrument"):
                inst.uninstrument()

            self._status[lib] = "uninstrumented"
            logger.info("Uninstrumented database library: %s", lib)
            return True

        except Exception:
            logger.debug("Uninstrumentation failed for %s", lib, exc_info=True)
            return False

    # ----------------------------------------------------------------------
    def status(self) -> Dict[str, str]:
        """Return the instrumentation status for each library."""
        return dict(self._status)
