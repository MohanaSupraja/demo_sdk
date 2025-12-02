import logging
from typing import Dict, Any
from ..config import TelemetryConfig

logger = logging.getLogger(__name__)


def setup_otel(config: TelemetryConfig) -> Dict[str, Any]:
    """
    PRODUCTION-READY OpenTelemetry setup:
    - Traces (HTTP/gRPC)
    - Metrics (HTTP/gRPC)
    - Compression + batching
    - Safe fallback to console exporters
    - Compatible with OTEL 1.38.0
    """

    providers = {
        "tracer_provider": None,
        "meter_provider": None,
        "logger_provider": None,
    }

    try:
        # Base OTEL imports
        from opentelemetry.sdk.resources import Resource
        from opentelemetry import trace, metrics
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.metrics import MeterProvider

        from opentelemetry.sdk.trace.export import (
            BatchSpanProcessor,
            ConsoleSpanExporter,
        )

        from opentelemetry.sdk.metrics.export import (
            PeriodicExportingMetricReader,
            ConsoleMetricExporter,
        )

        # Exporters
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
            OTLPSpanExporter as GRPCSpanExporter,
        )
        from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import (
            OTLPMetricExporter as GRPCMetricExporter,
        )

        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter as HTTPSpanExporter,
        )
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
            OTLPMetricExporter as HTTPMetricExporter,
        )

        # Compression enum (required for OTEL >=1.30)
        from opentelemetry.exporter.otlp.proto.http._protocol import Compression

        # ------------------------------
        # 1. Resource
        # ------------------------------
        resource_attrs = config.resource_attributes or {}
        resource_attrs["service.name"] = config.service_name
        resource = Resource(attributes=resource_attrs)

        use_http = (config.protocol or "http/protobuf").startswith("http")

        # ===================================================================
        # 2. TRACES SETUP
        # ===================================================================

        try:
            tracer_provider = TracerProvider(resource=resource)

            # ---- Select exporter ----
            try:
                if config.collector_endpoint:
                    if use_http:
                        span_exporter = HTTPSpanExporter(
                            endpoint=f"{config.collector_endpoint}/v1/traces",
                            headers=config.headers or {},
                            compression=Compression.GZIP,
                            timeout=10000,
                        )
                    else:
                        span_exporter = GRPCSpanExporter(
                            endpoint=config.collector_endpoint,
                            insecure=config.insecure,
                            headers=config.headers or {},
                            compression="gzip",
                        )
                else:
                    span_exporter = ConsoleSpanExporter()

            except Exception as e:
                logger.warning("Falling back to ConsoleSpanExporter: %s", e)
                span_exporter = ConsoleSpanExporter()

            # ---- Add batch processor ----
            span_processor = BatchSpanProcessor(
                span_exporter,
                max_export_batch_size=config.max_export_batch_size,
                max_queue_size=config.max_queue_size,
                schedule_delay_millis=config.export_interval_ms,
            )
            tracer_provider.add_span_processor(span_processor)

            # ---- Prevent override warning ----
            from opentelemetry.trace import get_tracer_provider as gp
            if not isinstance(gp(), TracerProvider):
                trace.set_tracer_provider(tracer_provider)

            providers["tracer_provider"] = tracer_provider

        except Exception as e:
            logger.error("Tracer setup failed: %s", e)

        # ===================================================================
        # 3. METRICS SETUP (OTEL 1.38 — NO CUSTOM VIEWS)
        # ===================================================================

        try:
            # ---- Select metric exporter ----
            try:
                if config.collector_endpoint:
                    if use_http:
                        metric_exporter = HTTPMetricExporter(
                            endpoint=f"{config.collector_endpoint}/v1/metrics",
                            headers=config.headers or {},
                            compression=Compression.GZIP,
                            timeout=10000,
                        )
                    else:
                        metric_exporter = GRPCMetricExporter(
                            endpoint=config.collector_endpoint,
                            insecure=config.insecure,
                            headers=config.headers or {},
                        )
                else:
                    metric_exporter = ConsoleMetricExporter()

            except Exception as e:
                logger.warning("MetricExporter failed → using console: %s", e)
                metric_exporter = ConsoleMetricExporter()

            metric_reader = PeriodicExportingMetricReader(
                exporter=metric_exporter,
                export_interval_millis=config.export_interval_ms,
            )

            meter_provider = MeterProvider(
                resource=resource,
                metric_readers=[metric_reader],
            )

            metrics.set_meter_provider(meter_provider)
            providers["meter_provider"] = meter_provider

        except Exception as e:
            logger.error("Metrics setup failed: %s", e)

        # ------------------------------
        # LOGS handled separately
        # ------------------------------
        providers["logger_provider"] = None

    except Exception as e:
        logger.exception("Global OTEL setup failed: %s", e)

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