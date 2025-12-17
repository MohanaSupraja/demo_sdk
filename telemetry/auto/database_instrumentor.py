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
        - Safe fallback
        - Idempotent instrumentation
        - Clear tracing/logging template
        - Optional SQLAlchemy engine instrumentation
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
        "redis": (
            "opentelemetry.instrumentation.redis",
            "RedisInstrumentor",
        ),
        "pymongo": (
            "opentelemetry.instrumentation.pymongo",
            "PymongoInstrumentor",
        ),
    }

    def __init__(self):
        self._status: Dict[str, str] = {}  # lib -> "instrumented" / "uninstrumented"

    # ----------------------------------------------------------------------
    def instrument(
        self,
        libraries: List[str],
        sqlalchemy_engine: Optional[Any] = None
    ) -> Dict[str, bool]:
        """
        Auto-instrument configured database libraries.
        """

        results = {}

        for lib in libraries:
            lib = lib.lower()

            # -------------------------------------------------------------
            # Already instrumented
            # -------------------------------------------------------------
            if self._status.get(lib) == "instrumented":
                logger.debug(f"[DB-INSTRUMENTOR] {lib} already instrumented")
                results[lib] = True
                continue

            # -------------------------------------------------------------
            # Unknown library
            # -------------------------------------------------------------
            if lib not in self._INSTRUMENTOR_MAP:
                logger.debug(f"[DB-INSTRUMENTOR] No instrumentor registered for {lib}")
                results[lib] = False
                continue

            module_path, class_name = self._INSTRUMENTOR_MAP[lib]

            # -------------------------------------------------------------
            # Import instrumentor class
            # -------------------------------------------------------------
            try:
                mod = __import__(module_path, fromlist=[class_name])
                InstrumentorClass = getattr(mod, class_name)

            except Exception as e:
                logger.warning(
                    f"[DB-INSTRUMENTOR] Failed to import {class_name} for {lib}: {e}",
                    exc_info=True
                )
                results[lib] = False
                continue

            inst = InstrumentorClass()

            # -------------------------------------------------------------
            # Perform instrumentation
            # -------------------------------------------------------------
            try:

                # SQLAlchemy: engine provided → instrument engine
                if lib == "sqlalchemy" and sqlalchemy_engine is not None:
                    inst.instrument(engine=sqlalchemy_engine)

                else:
                    inst.instrument()

                self._status[lib] = "instrumented"

                logger.info(f"[DB-INSTRUMENTOR] Instrumented database library: {lib}")
                results[lib] = True

            except Exception as e:
                logger.error(
                    f"[DB-INSTRUMENTOR] Instrumentation FAILED for {lib}: {e}",
                    exc_info=True
                )
                results[lib] = False

        return results

    # ----------------------------------------------------------------------
    def uninstrument(self, lib: str) -> bool:
        """Undo instrumentation for a given database library."""
        lib = lib.lower()

        if lib not in self._INSTRUMENTOR_MAP:
            return False

        module_path, class_name = self._INSTRUMENTOR_MAP[lib]

        try:
            mod = __import__(module_path, fromlist=[class_name])
            InstrumentorClass = getattr(mod, class_name)
            inst = InstrumentorClass()
        except Exception:
            return False

        try:
            if hasattr(inst, "uninstrument"):
                inst.uninstrument()

            self._status[lib] = "uninstrumented"
            logger.info(f"[DB-INSTRUMENTOR] Uninstrumented {lib}")
            return True

        except Exception:
            logger.debug(
                f"[DB-INSTRUMENTOR] Uninstrumentation failed for {lib}",
                exc_info=True
            )
            return False

    # ----------------------------------------------------------------------
    def status(self) -> Dict[str, str]:
        """Return instrumentation status of all DB libs."""
        return dict(self._status)

