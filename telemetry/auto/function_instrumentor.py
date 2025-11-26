import functools
import logging
from opentelemetry.trace import StatusCode

logger = logging.getLogger(__name__)


# Reuse the same telemetry resolver used everywhere else
from telemetry.auto.decorators import _resolve_telemetry


def instrument_function(func, name=None):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):

        tele = _resolve_telemetry(args[0] if args else None, func)
        span_name = name or func.__name__

        # -------------------------------
        # Case 1: Telemetry instance exists
        # -------------------------------
        if tele:
            tracer = tele.traces.tracer
            span = None
            try:
                with tracer.start_as_current_span(span_name) as s:
                    span = s
                    return func(*args, **kwargs)

            except Exception as e:
                try:
                    if span:
                        span.record_exception(e)
                        span.set_status(StatusCode.ERROR)
                except:
                    pass
                raise

        # -------------------------------
        # Case 2: Fallback to global tracer
        # -------------------------------
        try:
            from opentelemetry import trace
            tracer = trace.get_tracer(__name__)
            span = None

            try:
                with tracer.start_as_current_span(span_name) as s:
                    span = s
                    return func(*args, **kwargs)

            except Exception as e:
                try:
                    if span:
                        span.record_exception(e)
                        span.set_status(StatusCode.ERROR)
                    else:
                        cur = trace.get_current_span()
                        cur.record_exception(e)
                        cur.set_status(StatusCode.ERROR)
                except:
                    pass
                raise

        except Exception:
            # If tracer cannot be created, run function normally
            return func(*args, **kwargs)

    # propagate telemetry instance
    wrapper._telemetry = getattr(func, "_telemetry", None)
    return wrapper



class FunctionInstrumentor:
    def instrument(self, func, name=None):
        return instrument_function(func, name)
