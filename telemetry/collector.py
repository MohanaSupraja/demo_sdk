import logging
from typing import Optional, List, Dict, Any

from .config import TelemetryConfig
from .core.otel_setup import setup_otel
from .traces import TracesManager
from .metrics import MetricsManager
from .logs import LogsManager

from .auto.library_instrumentor import LibraryInstrumentor
from .auto.framework_instrumentor import FrameworkInstrumentor
from .auto.sify_sdk_instrumentor import SifySDKInstrumentor
from .auto.function_instrumentor import FunctionInstrumentor
from .auto.class_instrumentor import ClassInstrumentor
from .auto.decorators import create_decorators

logger = logging.getLogger(__name__)


class TelemetryCollector:
    def __init__(self, config: Optional[TelemetryConfig] = None):
        self.config = config or TelemetryConfig()

        # Setup OTel providers for traces/metrics
        providers = setup_otel(self.config)

        self.tracer_provider = providers.get("tracer_provider")
        self.meter_provider = providers.get("meter_provider")
        self.logger_provider = providers.get("logger_provider")

        # Managers
        self._traces = TracesManager(self.tracer_provider)
        self._metrics = MetricsManager(self.meter_provider)

        # FIXED: pass config to LogsManager
        self._logs = LogsManager(self.config)

        # Instrumentors
        self._lib_instrumentor = LibraryInstrumentor()
        self._fw_instrumentor = FrameworkInstrumentor()
        self._sify_instrumentor = SifySDKInstrumentor()
        self._func_instrumentor = FunctionInstrumentor()
        self._class_instrumentor = ClassInstrumentor()

        self._decorators = create_decorators(self)

        self._instrumented_libraries = set()

        # 1. Auto-instrument libraries
        if self.config.auto_instrument and self.config.instrument_libraries:
            try:
                self.enable_auto_instrumentation(self.config.instrument_libraries)
            except Exception as e:
                logger.debug(f"Library auto-instrumentation failed: {e}")

        # 2. Auto-instrument frameworks (Flask / FastAPI)
        if self.config.auto_instrument and self.config.instrument_frameworks:
            try:
                logger.debug("Auto-instrumenting framework...")
                # this will detect flask automatically
                self._fw_instrumentor.instrument_app(self.config.framework_app)
            except Exception as e:
                logger.debug(f"Framework auto-instrumentation failed: {e}")


    # Properties
    @property
    def traces(self):
        return self._traces

    @property
    def metrics(self):
        return self._metrics

    @property
    def logs(self):
        return self._logs

    @property
    def decorators(self):
        return self._decorators

    # Auto instrumentation
    def enable_auto_instrumentation(self, libraries: Optional[List[str]] = None):
        libs = libraries or self.config.instrument_libraries or []
        self._lib_instrumentor.instrument(libs)
        self._instrumented_libraries.update(libs)
        logger.info(f"Enabled auto-instrumentation for: {libs}")
        return True

    def disable_auto_instrumentation(self):
        for lib in list(self._instrumented_libraries):
            try:
                self._lib_instrumentor.uninstrument(lib)
            except Exception:
                pass
        self._instrumented_libraries.clear()
        logger.info("Disabled auto-instrumentation")
        return True
    
    def instrument_sdk_module(self, module_path: str, class_predicate=None):
        """
        Import module by path and instrument all classes found.
        - module_path: import path, e.g. "my_sdk.model_service"
        - class_predicate: optional callable(cls)->bool to filter which classes to instrument
        """
        try:
            mod = __import__(module_path, fromlist=["*"])
        except Exception as e:
            logger.debug("instrument_sdk_module import failed: %s", e, exc_info=True)
            return False

        from telemetry.auto.sify_sdk_instrumentor import SifySDKInstrumentor
        instr = SifySDKInstrumentor(telemetry=self)
        count = 0
        for name, obj in vars(mod).items():
            try:
                if isinstance(obj, type):
                    if class_predicate and not class_predicate(obj):
                        continue
                    # instrument the class
                    try:
                        instr.instrument_class(obj)
                        count += 1
                    except Exception:
                        logger.debug("instrument_class failed for %s", obj, exc_info=True)
            except Exception:
                continue
        logger.info("Instrumented %d classes in module %s", count, module_path)
        return True


    def instrument_library(self, library_name: str):
        self._lib_instrumentor.instrument([library_name])
        self._instrumented_libraries.add(library_name)
        return True

    def uninstrument_library(self, library_name: str):
        return self._lib_instrumentor.uninstrument(library_name)

    def get_instrumented_libraries(self) -> List[str]:
        return list(self._instrumented_libraries)

    def instrument_app(self, app: Any):
        return self._fw_instrumentor.instrument_app(app)

    # def instrument_class(self, cls, prefix: str = None):
    #     return self._sify_instrumentor.instrument_class(cls, prefix)
    def instrument_class(self, cls, prefix=None):
        return self._class_instrumentor.instrument(cls, self, prefix)

    def instrument_function(self, func, name: str = None):
        return self._func_instrumentor.instrument(func, name)

    # Context propagation
    def inject_context(self, carrier: Dict[str, str], context=None):
        try:
            from .utils.context import inject
            inject(carrier, context)
        except Exception:
            pass
        return carrier

    def extract_context(self, carrier: Dict[str, str]):
        try:
            from .utils.context import extract
            return extract(carrier)
        except Exception:
            return None

    # Lifecycle methods
    def flush(self, timeout_ms: int = 30000) -> bool:
        try:
            if hasattr(self.tracer_provider, "force_flush"):
                self.tracer_provider.force_flush(timeout_ms / 1000.0)
                return True
        except Exception:
            pass
        return False

    def shutdown(self, timeout_ms: int = 30000) -> bool:
        try:
            if hasattr(self.tracer_provider, "shutdown"):
                self.tracer_provider.shutdown(timeout_ms / 1000.0)
        except Exception:
            pass
        return True

    def is_enabled(self) -> bool:
        return bool(
            self.config.enable_traces
            or self.config.enable_metrics
            or self.config.enable_logs
        )
