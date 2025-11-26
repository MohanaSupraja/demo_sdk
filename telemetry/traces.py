from typing import Dict, Any
from contextlib import contextmanager

try:
    from opentelemetry import trace
    from opentelemetry.trace import SpanKind, Status, StatusCode
except Exception:
    trace = None
    SpanKind = None
    Status = None
    StatusCode = None


class TracesManager:
    """
    Wrapper around OTel tracer that works with both:
    - OTLP HTTP exporter
    - OTLP gRPC exporter
    - fallback Dummy tracer

    Fix applied:
      → tracer must be created via get_tracer(__name__)
         AFTER tracer provider is set globally.

    This ensures spans generated here are exported through
    whatever exporter was configured in otel_setup.py.
    """

    def __init__(self, tracer_provider=None):
        self.tracer = None
        try:
            if trace:
                # -------------------------------------------
                # IMPORTANT FIX:
                #   tracer_provider argument is NOT supported.
                #   OTel always uses the GLOBAL tracer provider.
                #   So otel_setup.py must call:
                #       trace.set_tracer_provider(provider)
                #
                # Here we only call get_tracer().
                # -------------------------------------------
                if tracer_provider is not None:
                    # Optional: ensure provider is global
                    trace.set_tracer_provider(tracer_provider)

                self.tracer = trace.get_tracer(__name__)
        except Exception:
            self.tracer = None

    # ------------------------------------------------------------------
    # Context manager for spans
    # ------------------------------------------------------------------
    @contextmanager
    def start_span(self, name: str, attributes: Dict[str, Any] = None, kind=None):
        if self.tracer:
            with self.tracer.start_as_current_span(
                name,
                attributes=attributes,
                kind=kind
            ) as span:
                yield span
        else:
            # Dummy span fallback
            class DummySpan:
                def set_attribute(self, k, v): pass
                def add_event(self, *a, **k): pass
                def set_status(self, *a, **k): pass
                def record_exception(self, *a, **k): pass
                def end(self): pass
            yield DummySpan()

    # ------------------------------------------------------------------
    # Explicit context-managed span starter
    # ------------------------------------------------------------------
    def start_span_as_current(self, name: str, attributes: Dict[str, Any] = None, kind=None):
        if self.tracer:
            return self.tracer.start_as_current_span(
                name,
                attributes=attributes,
                kind=kind
            )

        class DummyCM:
            def __enter__(self): return None
            def __exit__(self, *a): return False

        return DummyCM()

    # ------------------------------------------------------------------
    # Manual span creator (not context-managed)
    # ------------------------------------------------------------------
    def create_span(self, name: str, attributes: Dict[str, Any] = None, kind=None):
        if self.tracer:
            return self.tracer.start_span(name, attributes=attributes, kind=kind)
        return None

    # ------------------------------------------------------------------
    # Get current active span
    # ------------------------------------------------------------------
    def get_current_span(self):
        try:
            if trace:
                return trace.get_current_span()
        except Exception:
            return None
        return None
