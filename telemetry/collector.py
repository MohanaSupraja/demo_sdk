import logging
from typing import Optional, List, Dict, Any
from .config import TelemetryConfig
from .core.otel_setup import setup_otel
from .core.traces import TracesManager
from .core.metrics import MetricsManager
from .core.logs import LogsManager
from .auto.library_instrumentor import LibraryInstrumentor
from .auto.framework_instrumentor import FrameworkInstrumentor
from .auto.database_instrumentor import DatabaseInstrumentor
from .auto.sify_sdk_instrumentor import SifySDKInstrumentor
from .auto.function_instrumentor import FunctionInstrumentor
from .auto.class_instrumentor import ClassInstrumentor
from .auto.decorators import create_decorators

logger = logging.getLogger(__name__)


class TelemetryCollector:
    def __init__(self, config: Optional[TelemetryConfig] = None):
        self.config = config or TelemetryConfig()

        # Setup OTel providers
        providers = setup_otel(self.config)

        self.tracer_provider = providers.get("tracer_provider")
        self.meter_provider = providers.get("meter_provider")
        self.logger_provider = providers.get("logger_provider")

        # Managers
        self._traces = TracesManager(self.tracer_provider)
        self._metrics = MetricsManager(self.meter_provider)
        self._logs = LogsManager(self.config, logger_provider=self.logger_provider)

        # Instrumentors
        self._lib_instrumentor = LibraryInstrumentor()
        self._fw_instrumentor = FrameworkInstrumentor()
        self._db_instrumentor = DatabaseInstrumentor()
        self._sify_instrumentor = SifySDKInstrumentor()
        self._func_instrumentor = FunctionInstrumentor()
        self._class_instrumentor = ClassInstrumentor()

        self._decorators = create_decorators(self)
        self._instrumented_libraries = set()

        # --------------------------------------------------------
        # 1️⃣ Auto-instrument Framework (Flask / Django / FastAPI)
        # --------------------------------------------------------
        if self.config.auto_instrument and self.config.instrument_frameworks:
            logger.debug("Auto-instrumenting framework...")
            try:
                if self.config.framework_app:
                    self._fw_instrumentor.instrument_app(self.config.framework_app)
            except Exception:
                logger.debug("Framework auto-instrumentation failed", exc_info=True)

        # --------------------------------------------------------
        # 2️⃣ Auto-instrument Libraries (requests, httpx, urllib3)
        # --------------------------------------------------------

        if (
            self.config.auto_instrument
            and self.config.instrument_libraries_enabled
            and self.config.instrument_libraries
        ):
            logger.debug(f"Auto-instrumenting libraries: {self.config.instrument_libraries}")
            try:
                results = self._lib_instrumentor.instrument(self.config.instrument_libraries)
                self._instrumented_libraries.update(self.config.instrument_libraries)
            except Exception:
                logger.debug("Library auto-instrumentation failed", exc_info=True)


        # --------------------------------------------------------
        # 3️⃣ Auto-instrument Databases
        # --------------------------------------------------------
        if (
            self.config.auto_instrument
            and self.config.instrument_databases_enabled
            and self.config.instrument_databases
        ):
            logger.debug(f"Auto-instrumenting DB clients: {self.config.instrument_databases}")
            try:
                self._db_instrumentor.instrument(self.config.instrument_databases)
            except Exception:
                logger.debug("Database instrumentation failed", exc_info=True)
        # --------------------------------------------------------
        # 4️⃣ Auto-instrument Python logging → Loki
        #     ✔ Captures ALL Python logs
        #     ✔ Injects trace_id/span_id
        #     ✔ Sends to OTEL → Collector → Loki
        # --------------------------------------------------------
        if self.config.enable_logs and self.config.auto_instrument:
            try:
                from opentelemetry.instrumentation.logging import LoggingInstrumentor
                LoggingInstrumentor().instrument(set_logging_format=True,excluded_loggers=[
                    "werkzeug",
                    "werkzeug._internal",
                    "werkzeug.serving",
                    "werkzeug.developmentserver",
                    "werkzeug.wsgi",
                    "gunicorn.access",
                    "uvicorn.access",
                ])
                self._enable_python_auto_log_capture()
                logger.debug("Python auto log capture enabled.")
            except Exception:
                logger.debug("Python logging auto-instrumentation failed", exc_info=True)

    # --------------------------------------------------------
    #  NEW METHOD: EXPORT NORMAL PYTHON LOGS → OTEL → LOKI
    # --------------------------------------------------------
    def _enable_python_auto_log_capture(self):
        import logging
        from opentelemetry.trace import get_current_span

        provider = self._logs.otel_logger_provider

        # DO NOT CALL set_logger_provider(provider) HERE ❌

        otel_logger = provider.get_logger(self.config.service_name)

        class OTelLoggingHandler(logging.Handler):
            def emit(self, record):
                try:
                    span_ctx = get_current_span().get_span_context()
                    trace_attrs = {}

                    if span_ctx and span_ctx.trace_id != 0:
                        trace_attrs = {
                            "trace_id": f"{span_ctx.trace_id:032x}",
                            "span_id": f"{span_ctx.span_id:016x}",
                        }

                    otel_logger.emit(
                        body=record.getMessage(),
                        severity_text=record.levelname,
                        severity_number=record.levelno,
                        attributes={
                            "logger.name": record.name,
                            "file": record.filename,
                            "line": record.lineno,
                            **trace_attrs,
                        },
                    )
                except Exception:
                    pass

        root = logging.getLogger()
        root.addHandler(OTelLoggingHandler())
        root.setLevel(logging.INFO)

    # ---------------- PROPERTIES ----------------
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

    # ---------------- PUBLIC API ----------------
    def enable_auto_instrumentation(self, libraries: Optional[List[str]] = None):
        libs = libraries or self.config.instrument_libraries or []
        self._lib_instrumentor.instrument(libs)
        self._instrumented_libraries.update(libs)
        return True

    def disable_auto_instrumentation(self):
        for lib in list(self._instrumented_libraries):
            try:
                self._lib_instrumentor.uninstrument(lib)
            except Exception:
                pass
        self._instrumented_libraries.clear()
        return True

    def instrument_database(self, db_libs: List[str]):
        return self._db_instrumentor.instrument(db_libs)

    def instrument_library(self, library_name: str):
        self._lib_instrumentor.instrument([library_name])
        self._instrumented_libraries.add(library_name)
        return True

    def instrument_app(self, app: Any, framework: str = None):
        return self._fw_instrumentor.instrument_app(app, framework)

    def instrument_class(self, cls, prefix=None):
        return self._class_instrumentor.instrument(cls, self, prefix)
    

    def instrument_function(self, func, name: str = None):

        print(" [Collector.instrument_function] Called", flush=True)
        print(f"    ➤ func original: {func} (id={id(func)})", flush=True)
        print(f"    ➤ func name: {func.__name__}", flush=True)

        # Avoid double wrapping
        if getattr(func, "__wrapped_by_sdk__", False):
            print("     Function already wrapped, returning existing wrapper", flush=True)
            return func

        # Ask FunctionInstrumentor to wrap the function
        wrapped = self._func_instrumentor.instrument(func, name)
        print(f"    ✔ Wrapper created: {wrapped} (id={id(wrapped)})", flush=True)
        print(f"    ✔ Wrapper __name__ = {wrapped.__name__}", flush=True)

        # Attach telemetry so wrapper can use it
        wrapped._telemetry = self
        wrapped.__wrapped_by_sdk__ = True

        print(f"     Attached TelemetryCollector to wrapper _telemetry={wrapped._telemetry}", flush=True)

        # EXTRA DEBUG - Check mapping
        try:
            instrumentor_map = self._func_instrumentor._wrapped
            if func in instrumentor_map:
                print(f"    Mapping found: {func} → {instrumentor_map[func]}", flush=True)
            else:
                print("     Mapping NOT found inside FunctionInstrumentor!", flush=True)
        except Exception as e:
            print(f"     Failed to inspect FunctionInstrumentor mapping: {e}", flush=True)

        print(" [Collector.instrument_function] DONE\n", flush=True)

        return wrapped



    # ---------------- CONTEXT ----------------
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

    # ---------------- LIFECYCLE ----------------
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

    # def is_enabled(self) -> bool:
    #     return bool(
    #         self.config.enable_traces
    #         or self.config.enable_metrics
    #         or self.config.enable_logs
    #     )
