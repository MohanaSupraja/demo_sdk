import logging
import inspect
import functools
import time
from typing import Optional, Any
from opentelemetry.trace import StatusCode

logger = logging.getLogger(__name__)


class SifySDKInstrumentor:
    """
    Production-grade SDK Class Instrumentor.

    Provides:
    - Tracing      → span per method
    - Metrics      → call counter + duration histogram + errors
    - Logging      → success/error logs with trace correlation
    - Async/Sync   → automatically supported
    - Safe fallback → never breaks user code
    """

    def __init__(self, telemetry: Optional[Any] = None, tracer_name: str = __name__):
        self.telemetry = telemetry
        self.tracer_name = tracer_name
        self._wrapped = {}

    # --------------------------------------------------------------------
    # TRACER RESOLUTION (safe)
    # --------------------------------------------------------------------
    def _get_tracer(self):
        try:
            if self.telemetry and hasattr(self.telemetry, "traces"):
                return self.telemetry.traces.tracer
        except Exception:
            pass

        # fallback → global tracer
        try:
            from opentelemetry import trace
            return trace.get_tracer(self.tracer_name)
        except Exception:
            return None

    # --------------------------------------------------------------------
    # METRICS HELPERS (safe)
    # --------------------------------------------------------------------
    def _increment_counter(self, name: str, value: float = 1.0, attributes=None):
        attrs = attributes or {}
        try:
            if self.telemetry and hasattr(self.telemetry, "metrics"):
                self.telemetry.metrics.increment_counter(name, value, attrs)
        except Exception:
            logger.debug("Counter metric failed: %s", name, exc_info=True)

    def _record_histogram(self, name: str, value: float, attributes=None):
        attrs = attributes or {}
        try:
            if self.telemetry and hasattr(self.telemetry, "metrics"):
                self.telemetry.metrics.record_histogram(name, value, attrs)
        except Exception:
            logger.debug("Histogram metric failed: %s", name, exc_info=True)

    # --------------------------------------------------------------------
    # LOGGING HELPERS (safe)
    # --------------------------------------------------------------------
    def _emit_log(self, level: str, message: str, attributes=None):
        attrs = attributes or {}

        # Preferred path → SDK logs
        try:
            if self.telemetry and hasattr(self.telemetry, "logs"):
                getattr(self.telemetry.logs, level)(message, attrs)
                return
        except Exception:
            logger.debug("telemetry.logs failed", exc_info=True)

        # Fallback → Python logger with trace IDs
        try:
            from opentelemetry.trace import get_current_span
            span = get_current_span()
            sc = span.get_span_context()
            if sc and sc.trace_id != 0:
                attrs["trace_id"] = f"{sc.trace_id:032x}"
                attrs["span_id"] = f"{sc.span_id:016x}"
        except Exception:
            pass

        logging.getLogger("sify.sdk").info(f"{message} | attrs={attrs}")

    # --------------------------------------------------------------------
    # INSTRUMENT A CLASS (main method)
    # --------------------------------------------------------------------
    def instrument_class(self, cls: type, prefix: Optional[str] = None) -> bool:
        """
        Wrap all public methods with tracing + metrics + logs.
        """

        for method_name, method in inspect.getmembers(cls, predicate=inspect.isfunction):
            if method_name.startswith("_"):
                continue  # skip private/internal

            if getattr(method, "_sify_wrapped", False):
                continue  # avoid double wrapping

            original = getattr(cls, method_name)

            # Metric/log naming
            base_prefix = f"{prefix}." if prefix else ""
            base_name = f"{base_prefix}{cls.__name__}.{method_name}"
            counter_name = f"{base_name}.calls"
            error_counter = f"{base_name}.errors"
            histogram_name = f"{base_name}.duration_ms"

            # --------------------------
            # BUILD WRAPPER
            # --------------------------
            def make_wrapper(orig=original, mname=method_name):

                # -------- ASYNC FUNCTION --------
                if inspect.iscoroutinefunction(orig):

                    async def async_wrapper(*args, **kwargs):
                        tracer = self._get_tracer()
                        start = time.perf_counter()
                        span = None
                        success = False

                        try:
                            if tracer:
                                with tracer.start_as_current_span(f"{cls.__name__}.{mname}") as span:
                                    span.set_attribute("sify.class", cls.__name__)
                                    span.set_attribute("sify.method", mname)
                                    result = await orig(*args, **kwargs)
                            else:
                                result = await orig(*args, **kwargs)

                            success = True
                            return result

                        except Exception as exc:
                            if span:
                                try:
                                    span.record_exception(exc)
                                    span.set_status(StatusCode.ERROR)
                                except Exception:
                                    pass
                            raise

                        finally:
                            elapsed = (time.perf_counter() - start) * 1000
                            base_attrs = {
                                "class": cls.__name__,
                                "method": mname,
                                "success": success,
                            }

                            # METRICS
                            self._increment_counter(counter_name, 1, base_attrs)
                            if not success:
                                self._increment_counter(error_counter, 1, base_attrs)
                            self._record_histogram(histogram_name, elapsed, base_attrs)

                            # LOGS
                            level = "info" if success else "error"
                            self._emit_log(level, f"{mname} executed", {**base_attrs, "duration_ms": elapsed})

                    async_wrapper._sify_wrapped = True
                    return functools.wraps(orig)(async_wrapper)

                # -------- SYNC FUNCTION --------
                else:
                    def wrapper(*args, **kwargs):
                        tracer = self._get_tracer()
                        start = time.perf_counter()
                        span = None
                        success = False

                        try:
                            if tracer:
                                with tracer.start_as_current_span(f"{cls.__name__}.{mname}") as span:
                                    span.set_attribute("sify.class", cls.__name__)
                                    span.set_attribute("sify.method", mname)
                                    result = orig(*args, **kwargs)
                            else:
                                result = orig(*args, **kwargs)

                            success = True
                            return result

                        except Exception as exc:
                            if span:
                                try:
                                    span.record_exception(exc)
                                    span.set_status(StatusCode.ERROR)
                                except Exception:
                                    pass
                            raise

                        finally:
                            elapsed = (time.perf_counter() - start) * 1000
                            base_attrs = {
                                "class": cls.__name__,
                                "method": mname,
                                "success": success,
                            }

                            # METRICS
                            self._increment_counter(counter_name, 1, base_attrs)
                            if not success:
                                self._increment_counter(error_counter, 1, base_attrs)
                            self._record_histogram(histogram_name, elapsed, base_attrs)

                            # LOGS
                            level = "info" if success else "error"
                            self._emit_log(level, f"{mname} executed", {**base_attrs, "duration_ms": elapsed})

                    wrapper._sify_wrapped = True
                    return functools.wraps(orig)(wrapper)

            setattr(cls, method_name, make_wrapper())

        logger.info(f"Instrumented SDK class: {cls.__name__}")
        return True


"""
SDK-level instrumentation automatically adds traces, metrics, and logs to every method inside YOUR SDK, without the user needing to write decorators or modify code.

It turns your SDK into a self-observable library, just like AWS SDK, Stripe SDK, MongoDB drivers, etc.

When someone imports and uses your SDK:

Every SDK method call becomes a trace span

Performance metrics (latency, call count, errors) are recorded

Logs with trace correlation are emitted

Async & sync methods are handled

Errors automatically generate spans + logs

All of this happens inside your SDK, before the user writes any code.

⭐ How SDK-Level Instrumentation Is Used

You enable it once during SDK initialization:

from telemetry.sdk.sdk_instrumentor import SifySDKInstrumentor
from telemetry import Telemetry

tele = Telemetry()
instrumentor = SifySDKInstrumentor(tele)

from sify_sdk.client import SifyClient
instrumentor.instrument_class(SifyClient)



✅ Example SDK Class (Before Instrumentation)

Imagine your SDK provides this class to users:

# file: sify_sdk/client.py

class SifyClient:
    def connect(self, endpoint):
        print("Connecting...")
        return True

    def fetch_data(self, id):
        if id == 0:
            raise ValueError("Invalid ID")
        return {"id": id, "value": 100}

    async def async_process(self, value):
        return value * 2


✅ Apply SDK-Level Instrumentation

In your SDK startup:

from telemetry.sdk.sdk_instrumentor import SifySDKInstrumentor
from telemetry import Telemetry  # your unified Telemetry object

tele = Telemetry()
sdk_inst = SifySDKInstrumentor(telemetry=tele)

# instrument the entire class
from sify_sdk.client import SifyClient
sdk_inst.instrument_class(SifyClient)

🎉 After Instrumentation — What Happens Automatically

Now all methods in SifyClient get:

✔ Tracing

Every method call produces a span:

SifyClient.connect
SifyClient.fetch_data
SifyClient.async_process

✔ Metrics

Automatically generated:

SifyClient.connect.calls          → number of calls
SifyClient.connect.duration_ms    → execution time
SifyClient.connect.errors         → error count

✔ Logs

Structured logs:

"method": "connect",
"success": true,
"duration_ms": 3.43


If fetch_data fails:

"method": "fetch_data",
"success": false,
"exception": "ValueError"

✔ Async Supported

async_process() is wrapped safely with async tracing & metrics.


"""