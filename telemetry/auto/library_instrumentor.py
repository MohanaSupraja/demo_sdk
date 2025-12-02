import logging
from typing import List, Dict, Any
import inspect

logger = logging.getLogger(__name__)

class LibraryInstrumentor:
    """
    Instruments libraries: requests, urllib3, httpx, aiohttp, logging.
    """

    _INSTRUMENTOR_MAP = {
        "requests": ("opentelemetry.instrumentation.requests", "RequestsInstrumentor"),
        "urllib3": ("opentelemetry.instrumentation.urllib3", "URLLib3Instrumentor"),
        "httpx": ("opentelemetry.instrumentation.httpx", "HTTPXClientInstrumentor"),
        "aiohttp": ("opentelemetry.instrumentation.aiohttp_client", "AioHttpClientInstrumentor"),
        "logging": ("opentelemetry.instrumentation.logging", "LoggingInstrumentor"),
    }

    def __init__(self):
        self._status: Dict[str, str] = {}

    # --------------------------------------------------------------
    def instrument(self, libs: List[str]) -> Dict[str, bool]:
        results = {}

        for lib in libs:
            lib = lib.lower()

            if self._status.get(lib) == "instrumented":
                results[lib] = True
                continue

            if lib not in self._INSTRUMENTOR_MAP:
                logger.debug("No instrumentor mapped for %s", lib)
                results[lib] = False
                continue

            module_path, class_name = self._INSTRUMENTOR_MAP[lib]

            try:
                mod = __import__(module_path, fromlist=[class_name])
                InstrumentorClass = getattr(mod, class_name)
            except Exception as e:
                logger.debug("Failed to import %s: %s", lib, e, exc_info=True)
                results[lib] = False
                continue

            inst = InstrumentorClass()

            # Special handling → logging
            if lib == "logging":
                try:
                    sig = inspect.signature(inst.instrument)
                    if "log_hook" in sig.parameters:
                        inst.instrument(log_hook=None)
                    else:
                        inst.instrument()
                except:
                    inst.instrument()

                self._status[lib] = "instrumented"
                results[lib] = True
                continue

            # Generic library instrumentation
            try:
                inst.instrument()
                self._status[lib] = "instrumented"
                logger.info("Instrumented library: %s", lib)
                results[lib] = True
            except Exception as e:
                logger.debug("Failed to instrument %s: %s", lib, e, exc_info=True)
                results[lib] = False

        return results

    # --------------------------------------------------------------
    def uninstrument(self, lib: str) -> bool:
        lib = lib.lower()

        if lib not in self._INSTRUMENTOR_MAP:
            return False

        module_path, class_name = self._INSTRUMENTOR_MAP[lib]

        try:
            mod = __import__(module_path, fromlist=[class_name])
            InstrumentorClass = getattr(mod, class_name)
        except:
            return False

        inst = InstrumentorClass()

        try:
            if hasattr(inst, "uninstrument"):
                inst.uninstrument()

            self._status[lib] = "uninstrumented"
            return True

        except:
            return False


    # ----------------------------------------------------------------
    def status(self) -> Dict[str, str]:
        return dict(self._status)




""" If auto_instrumentation = True

# Libraries are auto-instrumented based on instrument_libraries list.

# SDK imports the correct OTel instrumentor (requests, httpx, aiohttp, etc.).

# .instrument() is executed automatically.

# User does not need to configure anything manually.


# If auto_instrumentation = False

# No libraries are instrumented automatically.

# SDK does not import or modify any HTTP/logging library.

# User must explicitly call tele.instrument_library("requests") or provide a list.

# Only user-selected libraries are instrumented."""