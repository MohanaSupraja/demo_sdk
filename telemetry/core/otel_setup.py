import logging
from typing import Dict, Any
from ..config import TelemetryConfig

logger = logging.getLogger(__name__)


def setup_otel(config: TelemetryConfig) -> Dict[str, Any]:
    """
    PRODUCTION-GRADE OpenTelemetry Setup
    -------------------------------------
    • Traces → OTLP HTTP / gRPC
    • Metrics → OTLP HTTP / gRPC
    • Graceful fallbacks (console exporters)
    • Compression + retry-friendly
    • Safe TracerProvider initialization
    """

    providers = {
        "tracer_provider": None,
        "meter_provider": None,
        "logger_provider": None,
    }

    try:
        # Base imports
        from opentelemetry.sdk.resources import Resource
        from opentelemetry import trace, metrics
        from opentelemetry.sdk.trace import TracerProvider, SpanLimits
        from opentelemetry.sdk.metrics import MeterProvider

        from opentelemetry.sdk.trace.export import (
            BatchSpanProcessor,
            ConsoleSpanExporter,
        )
        from opentelemetry.sdk.metrics.export import (
            ConsoleMetricExporter,
            PeriodicExportingMetricReader,
        )

        # Exporters
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
            OTLPSpanExporter as GRPCSpanExporter
        )
        from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import (
            OTLPMetricExporter as GRPCMetricExporter
        )
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter as HTTPSpanExporter
        )
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
            OTLPMetricExporter as HTTPMetricExporter
        )

        # -------------------------------------------------------------
        # 1. RESOURCE ATTRIBUTES
        # -------------------------------------------------------------
        resource_attrs = config.resource_attributes or {}
        resource_attrs["service.name"] = config.service_name or "unknown-service"

        resource = Resource(attributes=resource_attrs)

        # Determine exporter mode
        endpoint = config.collector_endpoint or ""
        use_http = endpoint.startswith("http")

        # -------------------------------------------------------------
        # 2. TRACE PROVIDER + EXPORTER
        # -------------------------------------------------------------
        try:
            span_limits = SpanLimits(
                max_attributes=config.max_span_attributes or 128,
                max_events=256,
                max_links=128,
            )

            tracer_provider = TracerProvider(
                resource=resource,
                span_limits=span_limits,
            )

            # -------- SELECT TRACE EXPORTER --------
            try:
                if endpoint:
                    if use_http:
                        span_exporter = HTTPSpanExporter(
                            endpoint=f"{endpoint}/v1/traces",
                            headers=config.headers or {},
                            compression="gzip",
                            timeout=10000,
                        )
                    else:
                        span_exporter = GRPCSpanExporter(
                            endpoint=endpoint,
                            insecure=config.insecure,
                            headers=config.headers or {},
                            compression="gzip",
                        )
                else:
                    span_exporter = ConsoleSpanExporter()

            except Exception as e:
                logger.warning("Falling back to ConsoleSpanExporter: %s", e)
                span_exporter = ConsoleSpanExporter()

            processor = BatchSpanProcessor(
                span_exporter,
                max_export_batch_size=config.max_export_batch_size,
                max_queue_size=config.max_queue_size,
                schedule_delay_millis=config.export_interval_ms,
            )
            tracer_provider.add_span_processor(processor)

            # -------- SAFE SET TRACER PROVIDER --------
            from opentelemetry.sdk.trace import TracerProvider as SDKTracerProvider
            current = trace.get_tracer_provider()

            if not isinstance(current, SDKTracerProvider):
                trace.set_tracer_provider(tracer_provider)

            providers["tracer_provider"] = tracer_provider

        except Exception as e:
            logger.error("Trace setup failed: %s", e)

        # -------------------------------------------------------------
        # 3. METRICS PROVIDER + EXPORTER
        # -------------------------------------------------------------
        try:
            from opentelemetry.sdk.metrics.view import View
            from opentelemetry.sdk.metrics.aggregation import ExplicitBucketHistogramAggregation

            histogram_view = View(
                instrument_type="histogram",
                aggregation=ExplicitBucketHistogramAggregation(
                    [0, 10, 50, 100, 500, 1000, 2000]
                ),
            )

            # -------- SELECT METRIC EXPORTER --------
            try:
                if endpoint:
                    if use_http:
                        metric_exporter = HTTPMetricExporter(
                            endpoint=f"{endpoint}/v1/metrics",
                            headers=config.headers or {},
                            compression="gzip",
                            timeout=10000,
                        )
                    else:
                        metric_exporter = GRPCMetricExporter(
                            endpoint=endpoint,
                            insecure=config.insecure,
                            headers=config.headers or {},
                        )
                else:
                    metric_exporter = ConsoleMetricExporter()

            except Exception as e:
                logger.warning("Falling back to ConsoleMetricExporter: %s", e)
                metric_exporter = ConsoleMetricExporter()

            reader = PeriodicExportingMetricReader(
                metric_exporter,
                export_interval_millis=config.export_interval_ms,
            )

            meter_provider = MeterProvider(
                resource=resource,
                metric_readers=[reader],
                views=[histogram_view],
            )

            metrics.set_meter_provider(meter_provider)
            providers["meter_provider"] = meter_provider

        except Exception as e:
            logger.error("Metrics setup failed: %s", e)

        # -------------------------------------------------------------
        # Logs handled separately in LogsManager
        # -------------------------------------------------------------
        providers["logger_provider"] = None

    except Exception as e:
        logger.exception("FATAL: OTEL setup failed: %s", e)

    return providers





"""setup_otel() initializes OpenTelemetry Tracing + Metrics for your SDK:

Creates resource attributes like service.name

Creates and configures the TracerProvider

Creates and configures the MeterProvider

Selects OTLP HTTP or OTLP gRPC exporters based on config

Provides console fallback if OTEL exporter fails

Leaves logging to LogsManager (not handled here)

Returns a dict of initialized providers


providers contain the exporters and processors that actually send telemetry to endpoints.

Think of them as:

Provider = Manager
Processor = Worker
Exporter = Delivery System (HTTP → Collector → Jaeger/Prometheus/Loki)


| Provider           | What it manages                   | What gets exported            |
| ------------------ | --------------------------------- | ----------------------------- |
| **TracerProvider** | Span processors + span exporters  | → Jaeger, OTEL Collector      |
| **MeterProvider**  | Metric readers + metric exporters | → Prometheus / OTEL Collector |
| **LoggerProvider** | Log processors + log exporters    | → Loki / OTEL Collector       |


1️⃣ Provider created
tracer_provider = TracerProvider(resource=my_resource)

2️⃣ Exporter attached
span_exporter = OTLPSpanExporter(endpoint="http://otel-collector:4318")
processor = BatchSpanProcessor(span_exporter)
tracer_provider.add_span_processor(processor)

3️⃣ Provider is set globally
trace.set_tracer_provider(tracer_provider)


Now any tracer from this point:

tracer = trace.get_tracer(__name__)
with tracer.start_as_current_span("test"):
    ...


TracerProvider → BatchSpanProcessor → OTLP Exporter → Collector → Jaeger



"""