import functools
import time
import logging
from typing import Any, Dict
from opentelemetry.trace import StatusCode

logger = logging.getLogger(__name__)


# ======================================================================
#  TELEMETRY RESOLUTION
# ======================================================================
def _resolve_telemetry(self_or_fn, fn=None):
    """
    Resolve telemetry instance from:
    1. instance._telemetry (bound methods)
    2. fn._telemetry       (decorator binding)
    3. fn.__wrapped__._telemetry
    """
    try:
        if hasattr(self_or_fn, "_telemetry"):
            return getattr(self_or_fn, "_telemetry")
    except Exception:
        pass

    if fn and hasattr(fn, "_telemetry"):
        return getattr(fn, "_telemetry")

    if fn and hasattr(fn, "__wrapped__") and hasattr(fn.__wrapped__, "_telemetry"):
        return getattr(fn.__wrapped__, "_telemetry")

    return None


# ======================================================================
#  TRACE DECORATOR (COMPLETE, SAFE, ERROR-CAPTURING)
# ======================================================================
def trace(name: str = None):
    def dec(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):

            tele = _resolve_telemetry(args[0] if args else None, fn)
            span_name = name or fn.__name__

            # -----------------------------------------------------------------
            # CASE 1: Telemetry instance found (preferred)
            # -----------------------------------------------------------------
            if tele:
                tracer = tele.traces.tracer
                span = None
                try:
                    with tracer.start_as_current_span(span_name) as s:
                        span = s
                        return fn(*args, **kwargs)

                except Exception as e:
                    # record exception safely
                    try:
                        if span:
                            span.record_exception(e)
                            span.set_status(StatusCode.ERROR)
                    except Exception:
                        pass
                    raise

            # -----------------------------------------------------------------
            # CASE 2: Fallback to global tracer
            # -----------------------------------------------------------------
            try:
                from opentelemetry import trace as ot_trace
                tracer = ot_trace.get_tracer(__name__)
                span = None

                try:
                    with tracer.start_as_current_span(span_name) as s:
                        span = s
                        return fn(*args, **kwargs)

                except Exception as e:
                    try:
                        if span:
                            span.record_exception(e)
                            span.set_status(StatusCode.ERROR)
                        else:
                            cur = ot_trace.get_current_span()
                            cur.record_exception(e)
                            cur.set_status(StatusCode.ERROR)
                    except Exception:
                        pass
                    raise

            except Exception:
                # absolute fallback, never break user code
                return fn(*args, **kwargs)

        wrapper._telemetry = getattr(fn, "_telemetry", None)
        return wrapper

    dec._telemetry = None
    return dec


# ======================================================================
#  CAPTURE EXCEPTIONS DECORATOR
# ======================================================================
def capture_exceptions():
    def dec(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except Exception as e:
                tele = _resolve_telemetry(args[0] if args else None, fn)
                if tele:
                    try:
                        span = tele.traces.get_current_span()
                        if span:
                            span.record_exception(e)
                    except Exception:
                        pass
                raise

        wrapper._telemetry = getattr(fn, "_telemetry", None)
        return wrapper

    dec._telemetry = None
    return dec


# ======================================================================
#  METRIC COUNTER DECORATOR
# ======================================================================
def metric_counter(name: str, attributes: Dict[str, Any] = None):
    def dec(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            tele = _resolve_telemetry(args[0] if args else None, fn)
            if tele:
                try:
                    tele.metrics.increment_counter(name, 1, attributes)
                except Exception:
                    pass
            return fn(*args, **kwargs)

        wrapper._telemetry = getattr(fn, "_telemetry", None)
        return wrapper

    dec._telemetry = None
    return dec


# ======================================================================
#  METRIC HISTOGRAM DECORATOR
# ======================================================================
def metric_histogram(name: str, attributes: Dict[str, Any] = None):
    def dec(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            start = time.time()
            result = fn(*args, **kwargs)
            duration = time.time() - start

            tele = _resolve_telemetry(args[0] if args else None, fn)
            if tele:
                try:
                    tele.metrics.record_histogram(name, duration, attributes)
                except Exception:
                    pass

            return result

        wrapper._telemetry = getattr(fn, "_telemetry", None)
        return wrapper

    dec._telemetry = None
    return dec


# ======================================================================
#  METRIC OBSERVABLE DECORATOR
# ======================================================================
def metric_observable(name: str):
    def dec(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            tele = _resolve_telemetry(args[0] if args else None, fn)
            if tele:
                try:
                    tele.metrics.register_observable(name, fn)
                except Exception:
                    pass
            return fn(*args, **kwargs)

        wrapper._telemetry = getattr(fn, "_telemetry", None)
        return wrapper

    dec._telemetry = None
    return dec


# ======================================================================
#  LOGGING DECORATORS
# ======================================================================
def _log(level: str, message: str, attributes: Dict[str, Any]):
    def dec(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            tele = _resolve_telemetry(args[0] if args else None, fn)
            if tele:
                try:
                    getattr(tele.logs, level)(message, attributes)
                except Exception as e:
                    logger.debug("Log decorator failure: %s", e)

            return fn(*args, **kwargs)

        wrapper._telemetry = getattr(fn, "_telemetry", None)
        return wrapper

    dec._telemetry = None
    return dec


def log_info(message: str, attributes: Dict[str, Any] = None):
    return _log("info", message, attributes or {})


def log_debug(message: str, attributes: Dict[str, Any] = None):
    return _log("debug", message, attributes or {})


def log_warning(message: str, attributes: Dict[str, Any] = None):
    return _log("warning", message, attributes or {})


def log_error(message: str, attributes: Dict[str, Any] = None):
    return _log("error", message, attributes or {})


def log_critical(message: str, attributes: Dict[str, Any] = None):
    return _log("critical", message, attributes or {})


def log_with_attributes(attributes: Dict[str, Any]):
    return log_info("function_called", attributes)


# ======================================================================
#  DECORATOR REGISTRY
# ======================================================================
def create_decorators(telemetry_instance):
    """
    Binds telemetry to all decorator factories so they work for
    standalone functions and class-bound methods.
    """
    decs = {
        "trace": trace,
        "capture_exceptions": capture_exceptions,
        "metric_counter": metric_counter,
        "metric_histogram": metric_histogram,
        "metric_observable": metric_observable,
        "measure": metric_histogram,
        "log_info": log_info,
        "log_debug": log_debug,
        "log_warning": log_warning,
        "log_error": log_error,
        "log_critical": log_critical,
        "log_with_attributes": log_with_attributes,
    }

    for name, dec in decs.items():
        dec._telemetry = telemetry_instance

    return decs
