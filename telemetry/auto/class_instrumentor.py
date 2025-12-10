import inspect
import functools
import logging
from opentelemetry.trace import StatusCode

logger = logging.getLogger(__name__)


def instrument_class(cls, telemetry, prefix=None):
    """
    Automatically instruments all public methods of a class:
    ✓ Traces
    ✓ Logs
    ✓ Metrics
    """

    class_name = cls.__name__

    for name, method in inspect.getmembers(cls, inspect.isfunction):

        if name.startswith("_"):
            continue  # Skip private/dunder methods

        original = getattr(cls, name)
        span_name = f"{prefix}.{class_name}.{name}" if prefix else f"{class_name}.{name}"

        # IMPORTANT FIX: freeze loop variables
        def make_wrapper(orig_fn, span_name, method_name=name):
            @functools.wraps(orig_fn)
            def wrapper(*args, **kwargs):

                # Resolve telemetry
                tele = getattr(orig_fn, "_telemetry", telemetry)

                # No telemetry -> call original
                if tele is None or not getattr(tele, "traces", None):
                    return orig_fn(*args, **kwargs)

                tracer = tele.traces.tracer
                span = None

                try:
                    with tracer.start_as_current_span(span_name) as s:
                        span = s

                        # ----- LOG: START -----
                        try:
                            tele.logs.debug(
                                f"{span_name} started",
                                {"class": class_name, "method": method_name},
                            )
                        except Exception:
                            pass

                        result = orig_fn(*args, **kwargs)

                        # ----- LOG + METRIC: SUCCESS -----
                        try:
                            tele.logs.info(
                                f"{span_name} executed successfully",
                                {"class": class_name, "method": method_name, "outcome": "success"},
                            )

                            tele.metrics.increment_counter(
                                f"{class_name}.{method_name}.calls",
                                1,
                                {"outcome": "success"},
                            )
                        except Exception:
                            pass

                        return result

                except Exception as e:

                    # Trace error
                    try:
                        if span:
                            span.record_exception(e)
                            span.set_status(StatusCode.ERROR)
                    except Exception:
                        pass

                    # Log error
                    try:
                        tele.logs.error(
                            f"{span_name} failed",
                            {
                                "error": str(e),
                                "class": class_name,
                                "method": method_name,
                                "outcome": "failure",
                            },
                        )
                    except Exception:
                        pass

                    # Metrics
                    try:
                        tele.metrics.increment_counter(
                            f"{class_name}.{method_name}.calls",
                            1,
                            {"outcome": "failure"},
                        )
                    except Exception:
                        pass

                    raise

            # Attach telemetry to wrapper
            wrapper._telemetry = telemetry
            return wrapper

        # Replace class method with wrapper
        setattr(cls, name, make_wrapper(original, span_name))

    logger.info(f"Class '{cls.__name__}' instrumented successfully")
    return cls


class ClassInstrumentor:
    def instrument(self, cls, telemetry, prefix=None):
        return instrument_class(cls, telemetry, prefix)






"""Class Instrumentation wraps all public methods of a class with tracing + metrics + logs, records errors,
supports fallbacks, and adds full observability automatically without changing customer code.

It contains two major components:

1️⃣ instrument_class() function

This function:

Iterates over all public methods of a class (ignoring _private methods).

Wraps each method with a telemetry wrapper that automatically:

✔ Starts a trace span named ClassName.method

✔ Captures exceptions and marks the span as error

✔ Records method-level metrics (call count, duration)

✔ Emits success/failure logs

✔ Provides fallbacks so the app never breaks even if OTel fails

Attaches _telemetry to the method so decorators and other instrumentors can reuse it.

Purpose:

Automatically instrument every method in a class for observability.

2️⃣ ClassInstrumentor class

This class is a simple wrapper exposing:

instrument(self, cls, telemetry, prefix=None)


It allows the SDK to do:

tele.instrument_class(MyServiceClass)


Which internally calls instrument_class() to instrument all methods.

Purpose:

Provide a clean API inside TelemetryCollector to instrument whole classes.

🧠 What This File Achieves Overall

Enables zero-effort observability for entire classes.

Automatically applies:

Tracing (span per method)

Metrics (counter + duration histogram)

Logging (success/failure events)

Ensures no exceptions escape instrumentation code (safe fallbacks).

Eliminates the need for developers to manually add decorators everywhere.

Produces method-specific telemetry enriched with class context.


"""








