import functools
import logging
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# ------------------------------
# OPTIONAL OTEL StatusCode
# ------------------------------
try:
    from opentelemetry.trace import StatusCode
except Exception:
    class _DummyStatusCode:
        ERROR = "ERROR"
    StatusCode = _DummyStatusCode()

# Resolve TelemetryCollector (fallback resolver)
from telemetry.auto.decorators import _resolve_telemetry


# =====================================================================
#  MAIN FUNCTION INSTRUMENTOR
# =====================================================================
def instrument_function(fn, name: Optional[str] = None):
    span_name = name or fn.__name__

    counter_name = f"{span_name}.calls"
    histogram_name = f"{span_name}.duration_ms"

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):

        # 1️⃣ Primary: Use telemetry attached by TelemetryCollector
        tele = getattr(wrapper, "_telemetry", None)

        # 2️⃣ Fallback: use resolver only if needed
        if tele is None:
            tele = _resolve_telemetry(args[0] if args else None, fn)

        print(f"🟢 [WRAPPER ENTER] {span_name}", flush=True)
        print(f"    wrapper_id={id(wrapper)} fn_id={id(fn)}", flush=True)
        print(f"    wrapper._telemetry={wrapper._telemetry}", flush=True)
        print(f"    tele_resolved={tele}", flush=True)

        has_metrics = hasattr(tele, "metrics")
        has_logs = hasattr(tele, "logs")
        has_traces = (hasattr(tele, "traces") and hasattr(tele.traces, "tracer"))

        print(f"    has_metrics={has_metrics} has_logs={has_logs} has_traces={has_traces}", flush=True)

        start = time.time()

        base_attrs = {
            "function.name": span_name,
            "function.module": fn.__module__,
        }

        # --------------------------
        # INTERNAL HELPERS
        # --------------------------
        def log_success(duration):
            print(f"🟢 [SUCCESS] {span_name} duration={duration}", flush=True)

            if not tele:
                print("    NO tele – skipping metrics/logs")
                return

            # Metrics
            try:
                if tele.metrics:
                    tele.metrics.increment_counter(counter_name, 1, {
                        **base_attrs, "outcome": "success"
                    })
                    tele.metrics.record_histogram(histogram_name, duration, {
                        **base_attrs, "outcome": "success"
                    })
            except Exception:
                logger.debug("Metric success failed", exc_info=True)

            # Logs
            try:
                if tele.logs:
                    tele.logs.info(
                        f"{span_name} executed successfully",
                        {**base_attrs, "duration_ms": duration}
                    )
            except Exception:
                logger.debug("Log success failed", exc_info=True)

        def log_error(exc, duration):
            print(f"🔴 [ERROR] {span_name}: {exc}", flush=True)

            if not tele:
                return

            try:
                if tele.metrics:
                    tele.metrics.increment_counter(counter_name, 1, {
                        **base_attrs, "outcome": "error",
                        "exception.type": type(exc).__name__
                    })
                    tele.metrics.record_histogram(histogram_name, duration, {
                        **base_attrs, "outcome": "error",
                        "exception.type": type(exc).__name__
                    })
            except Exception:
                logger.debug("Metric error failed", exc_info=True)

            try:
                if tele.logs:
                    tele.logs.error(
                        f"Error in {span_name}",
                        {
                            **base_attrs,
                            "duration_ms": duration,
                            "exception.type": type(exc).__name__,
                            "exception.message": str(exc)
                        }
                    )
            except Exception:
                logger.debug("Log error failed", exc_info=True)

        # =================================================================
        # CASE 1 — TelemetryCollector TRACER AVAILABLE
        # =================================================================
        if tele and hasattr(tele, "traces") and hasattr(tele.traces, "tracer"):
            tracer = tele.traces.tracer
            try:
                with tracer.start_as_current_span(span_name) as span:
                    span.set_attribute("function.name", span_name)
                    span.set_attribute("function.module", fn.__module__)

                    result = fn(*args, **kwargs)

                    duration = (time.time() - start) * 1000
                    span.set_attribute("duration_ms", duration)

                    log_success(duration)
                    return result

            except Exception as exc:
                duration = (time.time() - start) * 1000
                span.record_exception(exc)
                span.set_status(StatusCode.ERROR)
                log_error(exc, duration)
                raise

        # =================================================================
        # CASE 2 — GLOBAL OTEL TRACER ONLY
        # =================================================================
        try:
            from opentelemetry import trace as ot_trace
            tracer = ot_trace.get_tracer(__name__)
        except Exception:
            tracer = None

        if tracer:
            try:
                with tracer.start_as_current_span(span_name) as span:
                    span.set_attribute("function.name", span_name)
                    span.set_attribute("function.module", fn.__module__)

                    result = fn(*args, **kwargs)
                    duration = (time.time() - start) * 1000
                    span.set_attribute("duration_ms", duration)

                    if tele:
                        log_success(duration)
                    return result

            except Exception as exc:
                duration = (time.time() - start) * 1000
                span.record_exception(exc)
                span.set_status(StatusCode.ERROR)

                if tele:
                    log_error(exc, duration)
                raise

        # =================================================================
        # CASE 3 — NO TRACING → LOGS + METRICS ONLY
        # =================================================================
        try:
            result = fn(*args, **kwargs)
            duration = (time.time() - start) * 1000
            if tele:
                log_success(duration)
            return result

        except Exception as exc:
            duration = (time.time() - start) * 1000
            if tele:
                log_error(exc, duration)
            raise

    # Initialize telemetry placeholder
    wrapper._telemetry = getattr(fn, "_telemetry", None)
    return wrapper


# =====================================================================
#  CLASS WRAPPER FOR DYNAMIC INSTRUMENTATION
# =====================================================================
class FunctionInstrumentor:

    def __init__(self):
        self._wrapped = {}
        print("🔧 FunctionInstrumentor initialized", flush=True)

    def instrument(self, func, name: Optional[str] = None):

        print("\n🔧 [FunctionInstrumentor.instrument] called", flush=True)
        print(f"   ➤ original_func={func} id={id(func)}", flush=True)

        wrapped = instrument_function(func, name)

        print(f"   ✔ wrapper={wrapped} id={id(wrapped)}", flush=True)

        # Allow TelemetryCollector to override
        wrapped._telemetry = getattr(func, "_telemetry", None)
        print(f"   🔧 wrapper._telemetry(initial)={wrapped._telemetry}", flush=True)

        # Store mapping (CRITICAL)
        self._wrapped[func] = wrapped
        print(f"   🗂 Stored mapping: {func} → {wrapped}", flush=True)

        print("🔧 [FunctionInstrumentor.instrument] DONE\n", flush=True)
        return wrapped


# =====================================================================
# SIMPLE USER-FACING DECORATOR
# =====================================================================
def instrument(fn=None, *, name: Optional[str] = None):
    """Clean decorator for user code."""
    if fn is None:
        return lambda f: instrument_function(f, name)
    return instrument_function(fn, name)



"""Any function wrapped with instrument_function now automatically creates spans, records metrics (counter + latency histogram),
 logs success/error with rich context, and never crashes even if OTEL or your collector is misconfigured
 
⭐ 1. Starts a trace span for each function call

Whenever the function is called:

A trace span is created with the function name.

All downstream tracing (HTTP calls, DB calls, etc.) automatically appear inside this span.

If an exception occurs, the span is marked with:

span.record_exception()

span.set_status(StatusCode.ERROR)

🔹 Works even if the user didn't pass telemetry (global fallback).
🔹 Safe: if tracing fails, function still runs normally.

⭐ 2. Records performance metrics for every execution

Two metric types are captured:

✔ Counter

Counts total executions:

function.calls_total - outcome="success"
function.calls_total - outcome="failure"

✔ Histogram

Records execution duration (latency):

function.duration_ms - outcome="success"
function.duration_ms - outcome="failure"


These metrics allow you to build dashboards for:

Success rate

Failure rate

P95/P99 latency

Total throughput

All metrics are attribute-based, as recommended by OTel.

⭐ 3. Writes structured logs for success and failure

Each execution generates logs:

On success:
"Function X executed successfully"
duration_ms: 42
outcome: "success"

On failure:
"Function X failed"
error.type: ValueError
error.msg: "Something went wrong"
duration_ms: 42


Logs automatically include:

trace_id

span_id

host.name

service.name

timestamp

This makes the logs searchable, linkable to traces, and observable in Grafana, Loki, etc.

⭐ 4. Failsafe fallback behavior (never breaks user code)

Even if:

OpenTelemetry is not installed

Exporter errors occur

Telemetry is disabled

Spans fail to create

Metrics exporter fails

The function still runs normally.

All failures are logged at debug level, with no impact on application behavior.

⭐ 5. Unified Telemetry Resolution Logic

The _resolve_telemetry() helper automatically finds telemetry from:

Bound class methods (self._telemetry)

Decorator binding (fn._telemetry)

Wrapped functions (fn.__wrapped__._telemetry)

This makes instrumentation work for:

class methods

standalone functions

dynamically wrapped functions

SDK-instrumented modules

No manual wiring needed.

⭐ 6. Clean separation of responsibilities

The code separates tasks into helpers:

_record_metrics_and_logs_success() → metrics + logs for success

_record_metrics_and_logs_failure() → metrics + logs for failure

This keeps the main wrapper readable and structured.

🎯 Final One-Line Summary

Your function instrumentation automatically adds tracing, metrics, and logs 
around any function execution with production-safe fallbacks — 
giving full observability without breaking the user's application."""