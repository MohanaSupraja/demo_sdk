import logging
import inspect
import functools
import time
from typing import Optional, Any
from opentelemetry.trace import StatusCode

logger = logging.getLogger(__name__)


class SifySDKInstrumentor:
    """
    Instruments SDK classes:
    - Traces: span per method
    - Metrics: counter + histogram
    - Logs: emit contextual logs
    """

    def __init__(self, telemetry: Optional[Any] = None, tracer_name: str = __name__):
        self.telemetry = telemetry
        self.tracer_name = tracer_name
        self._wrapped = {}

    # -----------------------------------------------------------
    # TRACER LOAD
    # -----------------------------------------------------------
    def _get_tracer(self):
        try:
            if self.telemetry and hasattr(self.telemetry, "traces"):
                return self.telemetry.traces.tracer
        except Exception:
            pass
        try:
            from opentelemetry import trace
            return trace.get_tracer(self.tracer_name)
        except Exception:
            return None

    # -----------------------------------------------------------
    # METRICS HELPERS
    # -----------------------------------------------------------
    def _increment_counter(self, name: str, value: float = 1.0, attributes=None):
        attrs = attributes or {}
        try:
            if self.telemetry and hasattr(self.telemetry, "metrics"):
                self.telemetry.metrics.increment_counter(name, value, attrs)
                return
        except Exception:
            logger.debug("telemetry.metrics.increment_counter failed", exc_info=True)

    def _record_histogram(self, name: str, value: float, attributes=None):
        attrs = attributes or {}
        try:
            if self.telemetry and hasattr(self.telemetry, "metrics"):
                self.telemetry.metrics.record_histogram(name, value, attrs)
                return
        except Exception:
            logger.debug("telemetry.metrics.record_histogram failed", exc_info=True)

    # -----------------------------------------------------------
    # LOGGING
    # -----------------------------------------------------------
    def _emit_log(self, level: str, message: str, attributes=None):
        attrs = attributes or {}
        try:
            if self.telemetry and hasattr(self.telemetry, "logs"):
                getattr(self.telemetry.logs, level)(message, attrs)
                return
        except Exception:
            logger.debug("telemetry.logs failure", exc_info=True)

        # fallback logging with trace context
        try:
            from opentelemetry.trace import get_current_span
            span = get_current_span()
            ctx = {}
            sc = span.get_span_context()
            if sc and sc.trace_id != 0:
                ctx["trace_id"] = f"{sc.trace_id:032x}"
                ctx["span_id"] = f"{sc.span_id:016x}"
            merged = {**attrs, **ctx}
            logging.getLogger("sify.sdk").info(f"{message} | {merged}")
        except Exception:
            logging.getLogger("sify.sdk").info(f"{message} | attrs={attrs}")

    # -----------------------------------------------------------
    # CLASS INSTRUMENTATION
    # -----------------------------------------------------------
    def instrument_class(self, cls: type, prefix: Optional[str] = None) -> bool:

        for method_name, member in inspect.getmembers(cls, predicate=inspect.isfunction):
            if method_name.startswith("_"):
                continue

            original = getattr(cls, method_name)

            # avoid double wrapping
            if getattr(original, "_sify_wrapped", False):
                continue

            base = prefix + "." if prefix else ""
            base_name = f"{base}{cls.__name__}.{method_name}"
            counter_name = f"{base_name}.calls"
            hist_name = f"{base_name}.duration_ms"

            # bind local vars into closure
            def make_wrapper(orig=original, mname=method_name,
                             c_name=counter_name, h_name=hist_name):

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
                            attrs = {"class": cls.__name__, "method": mname, "success": success}
                            self._increment_counter(c_name, 1, attrs)
                            self._record_histogram(h_name, elapsed, attrs)
                            self._emit_log("info", f"{mname} executed", attrs)

                    async_wrapper._sify_wrapped = True
                    return functools.wraps(orig)(async_wrapper)

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
                                except:
                                    pass
                            raise

                        finally:
                            elapsed = (time.perf_counter() - start) * 1000
                            attrs = {"class": cls.__name__, "method": mname, "success": success}
                            self._increment_counter(c_name, 1, attrs)
                            self._record_histogram(h_name, elapsed, attrs)
                            self._emit_log("info", f"{mname} executed", attrs)

                    wrapper._sify_wrapped = True
                    return functools.wraps(orig)(wrapper)

            setattr(cls, method_name, make_wrapper())

        logger.info("Instrumented class %s", cls.__name__)
        return True






# import logging, inspect, functools
# logger = logging.getLogger(__name__)

# class SifySDKInstrumentor:
#     def __init__(self):
#         self._wrapped = {}

#     def instrument_class(self, cls, prefix: str = None):
#         for name, member in inspect.getmembers(cls, predicate=inspect.isfunction):
#             if name.startswith("_"): continue
#             original = getattr(cls, name)
#             def make_wrapper(orig, mname):
#                 def wrapper(*args, **kwargs):
#                     try:
#                         from opentelemetry import trace
#                         tracer = trace.get_tracer(__name__)
#                         with tracer.start_as_current_span(f"{cls.__name__}.{mname}"):
#                             return orig(*args, **kwargs)
#                     except Exception:
#                         return orig(*args, **kwargs)
#                 return functools.wraps(orig)(wrapper)
#             setattr(cls, name, make_wrapper(original, name))
#         logger.info("Instrumented class %s", cls)
#         return True
