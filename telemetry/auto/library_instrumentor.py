import logging
import inspect
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

class LibraryInstrumentor:
    """
    Central helper to instrument/uninstrument libraries (requests, logging, etc).
    Safely supports modern OpenTelemetry versions and avoids double-instrumentation.
    """

    _INSTRUMENTOR_MAP = {
        "requests": ("opentelemetry.instrumentation.requests", "RequestsInstrumentor"),
        "logging": ("opentelemetry.instrumentation.logging", "LoggingInstrumentor"),
    }

    def __init__(self):
        self._status: Dict[str, str] = {}

    # ----------------------------------------------------------------
    # INSTRUMENT
    # ----------------------------------------------------------------
    def instrument(self, libs: List[str]) -> Dict[str, bool]:
        results: Dict[str, bool] = {}

        for lib in libs:
            lib = lib.lower()

            # Already instrumented?
            if self._status.get(lib) == "instrumented":
                logger.debug("Skipping already instrumented library: %s", lib)
                results[lib] = True
                continue

            # No mapping?
            if lib not in self._INSTRUMENTOR_MAP:
                logger.debug("No instrumentor mapped for %s", lib)
                self._status[lib] = "missing"
                results[lib] = False
                continue

            module_path, class_name = self._INSTRUMENTOR_MAP[lib]

            # Import instrumentor class
            try:
                mod = __import__(module_path, fromlist=[class_name])
                InstrumentorClass = getattr(mod, class_name)
            except Exception as e:
                logger.debug("Failed to import %s: %s", lib, e, exc_info=True)
                self._status[lib] = "missing"
                results[lib] = False
                continue

            inst = InstrumentorClass()

            # ----------------------------------------------------------------------
            # SPECIAL HANDLING: Requests
            # Avoid double-instrumentation
            # ----------------------------------------------------------------------
            if lib == "requests":
                try:
                    if getattr(inst, "is_instrumented_by_opentelemetry", False):
                        logger.debug("Requests already instrumented, skipping")
                        self._status[lib] = "instrumented"
                        results[lib] = True
                        continue
                except Exception:
                    pass

            # ----------------------------------------------------------------------
            # SPECIAL HANDLING: Logging
            # Avoid double instrumentation + flexible signatures
            # ----------------------------------------------------------------------
            if lib == "logging":
                try:
                    sig = inspect.signature(inst.instrument)
                    if "log_hook" in sig.parameters:
                        inst.instrument(log_hook=None)
                    else:
                        inst.instrument()
                except Exception:
                    # fallback
                    try:
                        inst.instrument()
                    except Exception as e:
                        logger.debug("Logging instrument failed: %s", e, exc_info=True)
                        self._status[lib] = "failed"
                        results[lib] = False
                        continue

                self._status[lib] = "instrumented"
                results[lib] = True
                logger.info("Instrumented library: logging")
                continue

            # ----------------------------------------------------------------------
            # GENERIC INSTRUMENTATION
            # ----------------------------------------------------------------------
            try:
                inst.instrument()
                self._status[lib] = "instrumented"
                logger.info("Instrumented library: %s", lib)
                results[lib] = True
            except Exception as e:
                logger.debug("Failed to instrument %s: %s", lib, e, exc_info=True)
                self._status[lib] = "failed"
                results[lib] = False

        return results

    # ----------------------------------------------------------------
    # UNINSTRUMENT
    # ----------------------------------------------------------------
    def uninstrument(self, lib: str) -> bool:
        lib = lib.lower()

        if lib not in self._INSTRUMENTOR_MAP:
            return False

        module_path, class_name = self._INSTRUMENTOR_MAP[lib]

        try:
            mod = __import__(module_path, fromlist=[class_name])
            InstrumentorClass = getattr(mod, class_name)
        except Exception:
            self._status[lib] = "missing"
            return False

        inst = InstrumentorClass()

        try:
            if hasattr(inst, "uninstrument"):
                inst.uninstrument()
            elif hasattr(inst, "uninstrument_app"):
                inst.uninstrument_app()
            else:
                logger.debug("Instrumentor has no uninstrument()")
                return False

            self._status[lib] = "uninstrumented"
            logger.info("Uninstrumented library: %s", lib)
            return True

        except Exception as e:
            logger.debug("Failed to uninstrument %s: %s", lib, e, exc_info=True)
            self._status[lib] = "failed_uninstrument"
            return False

    # ----------------------------------------------------------------
    def status(self) -> Dict[str, str]:
        return dict(self._status)
