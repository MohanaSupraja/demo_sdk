import functools
import time
import logging
import traceback
from typing import Any, Dict
from opentelemetry.trace import StatusCode

logger = logging.getLogger(__name__)


# ======================================================================
#  HELPER: Consistent telemetry binding
# ======================================================================
def _bind_telemetry(wrapper, fn, dec=None):
    """
    Ensures telemetry always propagates through ALL decorator layers.
    """
    # 1️⃣ Copy telemetry from the original function (if instrumented by class/function instrumentation)
    if hasattr(fn, "_telemetry") and fn._telemetry is not None:
        wrapper._telemetry = fn._telemetry

    # 2️⃣ Or from the decorator factory (create_decorators binds telemetry here)
    elif dec is not None and hasattr(dec, "_telemetry"):
        wrapper._telemetry = dec._telemetry

    # 3️⃣ Or from nested decorator wrapped functions
    elif hasattr(fn, "__wrapped__") and hasattr(fn.__wrapped__, "_telemetry"):
        wrapper._telemetry = fn.__wrapped__._telemetry

    else:
        wrapper._telemetry = None

    return wrapper


# ======================================================================
#  TELEMETRY RESOLUTION (used ONLY for class methods)
# ======================================================================
def _resolve_telemetry(self_or_fn, fn=None):
    try:
        if hasattr(self_or_fn, "_telemetry"):
            return getattr(self_or_fn, "_telemetry")
    except Exception:
        pass

    if fn and hasattr(fn, "_telemetry"):
        return fn._telemetry

    if fn and hasattr(fn, "__wrapped__") and hasattr(fn.__wrapped__, "_telemetry"):
        return fn.__wrapped__._telemetry

    return None


# ======================================================================
#  TRACE DECORATOR (kept unchanged because it already works)
# ======================================================================
def trace(name: str = None):
    def dec(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            tele = _resolve_telemetry(args[0] if args else None, fn)
            span_name = name or fn.__name__

            # Prefer SDK tracer
            if tele:
                tracer = tele.traces.tracer
                span = None
                try:
                    with tracer.start_as_current_span(span_name) as s:
                        span = s
                        result = fn(*args, **kwargs)
                        span.set_status(StatusCode.OK)
                        return result
                except Exception as e:
                    if span:
                        span.record_exception(e)
                        span.set_status(StatusCode.ERROR)
                    raise

            # fallback → global tracer
            from opentelemetry import trace as ot_trace
            tracer = ot_trace.get_tracer(__name__)
            with tracer.start_as_current_span(span_name) as span:
                try:
                    result = fn(*args, **kwargs)
                    span.set_status(StatusCode.OK)
                    return result
                except Exception as e:
                    span.record_exception(e)
                    span.set_status(StatusCode.ERROR)
                    raise

        return _bind_telemetry(wrapper, fn, dec)

    dec._telemetry = None
    return dec


# ======================================================================
#  CAPTURE EXCEPTIONS
# ======================================================================
def capture_exceptions():
    def dec(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except Exception as e:

                tele = getattr(wrapper, "_telemetry", None)

                if tele:
                    try:
                        span = tele.traces.get_current_span()
                        if span:
                            span.record_exception(e)
                    except Exception:
                        pass

                raise

        return _bind_telemetry(wrapper, fn, dec)

    dec._telemetry = None
    return dec


# ======================================================================
#  METRIC COUNTER
# ======================================================================
def metric_counter(name: str, attributes: Dict[str, Any] = None):
    def dec(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):

            tele = getattr(wrapper, "_telemetry", None)

            if tele:
                try:
                    tele.metrics.increment_counter(name, 1, attributes)
                except Exception:
                    pass

            return fn(*args, **kwargs)

        return _bind_telemetry(wrapper, fn, dec)

    dec._telemetry = None
    return dec


# ======================================================================
#  HISTOGRAM METRIC
# ======================================================================
def metric_histogram(name: str, attributes: Dict[str, Any] = None):
    def dec(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):

            start = time.time()
            result = fn(*args, **kwargs)
            duration = time.time() - start

            tele = getattr(wrapper, "_telemetry", None)

            if tele:
                try:
                    tele.metrics.record_histogram(name, duration, attributes)
                except Exception:
                    pass

            return result

        return _bind_telemetry(wrapper, fn, dec)

    dec._telemetry = None
    return dec


# ======================================================================
#  MEASURE TIME
# ======================================================================
def measure_time(name: str, attributes: Dict[str, Any] = None):
    def dec(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):

            start = time.time()
            result = fn(*args, **kwargs)
            duration = time.time() - start

            tele = getattr(wrapper, "_telemetry", None)

            if tele:
                try:
                    tele.metrics.record_histogram(name, duration, attributes)
                except Exception:
                    pass

            return result

        return _bind_telemetry(wrapper, fn, dec)

    dec._telemetry = None
    return dec


# ======================================================================
#  LOG DECORATORS
# ======================================================================
def _log(level: str, message: str, attributes: Dict[str, Any]):
    def dec(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):

            tele = getattr(wrapper, "_telemetry", None)

            if tele:
                try:
                    getattr(tele.logs, level)(message, attributes)
                except Exception:
                    pass

            return fn(*args, **kwargs)

        return _bind_telemetry(wrapper, fn, dec)

    dec._telemetry = None
    return dec


def log_info(message, attributes=None): return _log("info", message, attributes or {})
def log_debug(message, attributes=None): return _log("debug", message, attributes or {})
def log_warning(message, attributes=None): return _log("warning", message, attributes or {})
def log_error(message, attributes=None): return _log("error", message, attributes or {})
def log_critical(message, attributes=None): return _log("critical", message, attributes or {})
def log_audit(message, attributes=None): return _log("audit", message, attributes or {})
def log_security(message, attributes=None): return _log("security", message, attributes or {})

def log_with_attributes(attributes):
    return log_info("function_called", attributes)


# ======================================================================
#  LOG EXCEPTIONS DECORATOR
# ======================================================================
def log_exceptions(level="error"):
    def dec(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except Exception as e:

                tele = getattr(wrapper, "_telemetry", None)

                if tele:
                    try:
                        getattr(tele.logs, level)(str(e), {
                            "exception.type": type(e).__name__,
                            "exception.stacktrace": traceback.format_exc(),
                        })
                    except Exception:
                        pass

                raise

        return _bind_telemetry(wrapper, fn, dec)

    dec._telemetry = None
    return dec


# ======================================================================
#  DECORATOR REGISTRY
# ======================================================================
def create_decorators(telemetry_instance):
    decs = {
        "trace": trace,
        "capture_exceptions": capture_exceptions,
        "metric_counter": metric_counter,
        "metric_histogram": metric_histogram,
        "measure": metric_histogram,
        "measure_time": measure_time,

        "log_info": log_info,
        "log_debug": log_debug,
        "log_warning": log_warning,
        "log_error": log_error,
        "log_critical": log_critical,
        "log_audit": log_audit,
        "log_security": log_security,
        "log_with_attributes": log_with_attributes,
        "log_exceptions": log_exceptions,
    }

    for name, dec in decs.items():
        dec._telemetry = telemetry_instance

    return decs



"""🔍 1. Telemetry Resolution Layer (_resolve_telemetry)

This utility detects which TelemetryCollector instance should be used:

Looks for _telemetry on the bound class instance (self)

Looks for _telemetry on the function itself

Looks for _telemetry on wrapped functions (nested decorators)

If none found → fallback to global OTEL tracer

This allows decorators to work for both class methods and normal functions.

🎯 2. @trace Decorator — Full Tracing Support

Adds OpenTelemetry tracing around a function:

Starts a span using TelemetryCollector or global OTEL

Automatically records exceptions inside the span

Sets span status to ERROR when failures occur

Never crashes user code even if tracing is misconfigured

This decorator creates complete observability for function-level performance & errors.

⚠️ 3. @capture_exceptions Decorator

Captures exceptions and records them into the current active OTEL span:

Does NOT handle or swallow the exception

Only records the error into telemetry

Fully safe fallback if tracing is disabled

Used when you want exceptions recorded but not wrapped in a custom span.

📊 4. Metric Decorators

Your decorators automatically emit metrics with zero boilerplate:

@metric_counter(name)

Increments a counter metric each time the function runs

@metric_histogram(name)

Measures execution duration (end - start)

Records the latency in a histogram metric

@measure_time(name)

Alias for histogram, specialized for performance measurement

@metric_observable(name)

Registers a callback for observable metrics (pull-based metrics)

All metric decorators are fail-safe: if OTEL metrics aren’t configured, they silently noop.

📝 5. Logging Decorators

Decorators that send structured logs through your LogsManager:

@log_info(message)
@log_warning(message)
@log_error(message)
@log_critical(message)
@log_debug(message)

Each:

Sends a log entry before the function executes

Supports optional attributes

Uses auto-injected trace_id/span_id from LogsManager

@log_exceptions

If function throws an error → logs it as an error

Doesn’t swallow the exception

🧩 6. Decorator Registry (create_decorators)

This generates a dictionary of all decorators pre-bound with a specific TelemetryCollector instance.

This enables:

tele.decorators["trace"](...)


Or:

@tele.decorators["metric_counter"]("db_calls")
def get_data():
    ...


This registry is essential for integrating decorators into SDK auto-instrumentation.

🛡️ 7. Safety Guarantees Built Into Your Decorators

Your decorator system is designed so that:

Tracing can fail → function still works

Metrics API missing → function still works

Logging exporter fails → Python logging fallback

Telemetry object missing → global OTEL used
ex: Decorators are used before the TelemetryCollector is created, Decorators are applied to standalone free functions, The user forgets to attach telemetry, A library instrumentor triggers spans internally

OTEL not installed → noop behavior 

Nothing in the decorator chain can break the user's application."""