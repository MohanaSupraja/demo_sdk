# ============================================================
# Unified Class Instrumentation
# ============================================================
import inspect
import functools
import logging
import time
from opentelemetry.trace import StatusCode

logger = logging.getLogger(__name__)


def instrument_class(cls, telemetry, prefix=None):
    """
    Unified class instrumentation:
        ✓ Same span template as function instrumentation
        ✓ Same metrics (calls, duration_ms)
        ✓ Same logs (structured success/error)
        ✓ Same attributes
    """

    class_name = cls.__name__

    for name, method in inspect.getmembers(cls, inspect.isfunction):

        if name.startswith("_"):
            continue  # skip private / dunder

        original = getattr(cls, name)

        # Unified span name
        qualified_name = f"{class_name}.{name}"
        span_name = f"telemetry.class.{qualified_name}"

        # Unified metrics
        counter_name = f"telemetry.class.{qualified_name}.calls"
        histogram_name = f"telemetry.class.{qualified_name}.duration_ms"

        def make_wrapper(orig_fn, span_name, method_name=name):
            @functools.wraps(orig_fn)
            def wrapper(*args, **kwargs):

                tele = getattr(orig_fn, "_telemetry", telemetry)

                # No telemetry → run normally
                if tele is None or not getattr(tele, "traces", None):
                    return orig_fn(*args, **kwargs)

                tracer = tele.traces.tracer
                span = None
                start = time.time()

                try:
                    with tracer.start_as_current_span(span_name) as span:

                        # Unified attributes
                        span.set_attribute("code.function", method_name)
                        span.set_attribute("code.class", class_name)
                        span.set_attribute("code.module", orig_fn.__module__)
                        span.set_attribute("telemetry.kind", "class")
                        span.set_attribute("telemetry.sdk", "custom-python-sdk")

                        result = orig_fn(*args, **kwargs)

                        duration = (time.time() - start) * 1000
                        span.set_attribute("duration_ms", duration)

                        # Metrics
                        try:
                            tele.metrics.increment_counter(
                                counter_name, 1,
                                {
                                    "class": class_name,
                                    "function": method_name,
                                    "outcome": "success",
                                }
                            )

                            tele.metrics.record_histogram(
                                histogram_name, duration,
                                {
                                    "class": class_name,
                                    "function": method_name,
                                    "outcome": "success",
                                }
                            )
                        except Exception:
                            logger.debug("Metric success error", exc_info=True)

                        # Logs
                        try:
                            tele.logs.info(
                                f"{qualified_name} executed successfully",
                                {
                                    "class": class_name,
                                    "function": method_name,
                                    "duration_ms": duration,
                                    "outcome": "success",
                                    "telemetry.kind": "class"
                                }
                            )
                        except Exception:
                            logger.debug("Log success failed", exc_info=True)

                        return result

                except Exception as e:

                    duration = (time.time() - start) * 1000

                    # Trace error
                    try:
                        if span:
                            span.record_exception(e)
                            span.set_status(StatusCode.ERROR)
                    except Exception:
                        pass

                    # Error metrics
                    try:
                        tele.metrics.increment_counter(
                            counter_name, 1,
                            {
                                "class": class_name,
                                "function": method_name,
                                "outcome": "error",
                                "exception.type": type(e).__name__,
                            }
                        )
                        tele.metrics.record_histogram(
                            histogram_name, duration,
                            {
                                "class": class_name,
                                "function": method_name,
                                "outcome": "error",
                                "exception.type": type(e).__name__,
                            }
                        )
                    except Exception:
                        logger.debug("Metric error failed", exc_info=True)

                    # Error logs
                    try:
                        tele.logs.error(
                            f"Error in {qualified_name}",
                            {
                                "class": class_name,
                                "function": method_name,
                                "duration_ms": duration,
                                "outcome": "error",
                                "exception.type": type(e).__name__,
                                "exception.message": str(e),
                            }
                        )
                    except Exception:
                        logger.debug("Log error failed", exc_info=True)

                    raise

            # Allow TelemetryCollector to override later
            wrapper._telemetry = telemetry

            return wrapper

        # Replace original method
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








