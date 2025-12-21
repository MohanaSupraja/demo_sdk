import logging
from typing import Dict, Any
from ..config import TelemetryConfig

logger = logging.getLogger(__name__)


def setup_otel(config: TelemetryConfig) -> Dict[str, Any]:
    """
    PRODUCTION-GRADE OpenTelemetry setup:
    - Traces (HTTP/gRPC)
    - Metrics (HTTP/gRPC)
    - Retry policies + compression
    - Span limits
    - Batch processor tuning
    - Safe fallbacks to console exporters
    """

    providers = {
        "tracer_provider": None,
        "meter_provider": None,
        "logger_provider": None,
    }

    try:
        from opentelemetry.sdk.resources import Resource
        from opentelemetry import trace, metrics
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.trace.export import (
            BatchSpanProcessor,
            ConsoleSpanExporter,
        )
        from opentelemetry.sdk.metrics.export import (
            ConsoleMetricExporter,
            PeriodicExportingMetricReader,
        )
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter as GRPCSpanExporter
        from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter as GRPCMetricExporter
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter as HTTPSpanExporter
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter as HTTPMetricExporter

        # -------------------------------------
        # 1️ RESOURCE (service.name, env, etc.)
        # -------------------------------------
        resource_attrs = config.resource_attributes or {}
        resource_attrs["service.name"] = config.service_name
        resource = Resource(attributes=resource_attrs)

        use_http = (config.protocol or "").startswith("http")

        # ===============================================================
        # 2️ TRACE PROVIDER + EXPORTER WITH RETRIES + COMPRESSION
        # ===============================================================
        try:
            # Span limits (important for production)
            from opentelemetry.sdk.trace import SpanLimits

            span_limits = SpanLimits(
                max_attributes=config.max_span_attributes or 128,
                max_events=256,
                max_links=128,
            )

            tracer_provider = TracerProvider(resource=resource, span_limits=span_limits)

            # Exporter Selection
            try:
                if config.collector_endpoint or use_http:

                    exporter_kwargs = {
                        "headers": config.headers or {},
                        "compression": "gzip",         # 🔥 enable compression
                        "timeout": 10_000,             # 🔥 ms timeout
                    }

                    if use_http:
                        span_exporter = HTTPSpanExporter(**exporter_kwargs)
                    else:
                        span_exporter = GRPCSpanExporter(
                            endpoint=config.collector_endpoint,
                            insecure=config.insecure,
                            **exporter_kwargs,
                        )
                else:
                    span_exporter = ConsoleSpanExporter()

            except Exception as e:
                logger.warning("OTLPSpanExporter failed, console fallback used: %s", e)
                span_exporter = ConsoleSpanExporter()

            # Batch Processor (tuned for production)
            span_processor = BatchSpanProcessor(
                span_exporter,
                max_export_batch_size=config.max_export_batch_size,
                max_queue_size=config.max_queue_size,
                schedule_delay_millis=config.export_interval_ms,
            )

            tracer_provider.add_span_processor(span_processor)
            trace.set_tracer_provider(tracer_provider)
            providers["tracer_provider"] = tracer_provider

        except Exception as e:
            logger.debug("Tracer setup failed: %s", e)

        # ===============================================================
        #  METRICS PROVIDER + EXPORTER WITH RETRIES + COMPRESSION
        # ===============================================================
        try:
            # Aggregation selector example (advanced tuning)
            from opentelemetry.sdk.metrics.view import View
            from opentelemetry.sdk.metrics.aggregation import ExplicitBucketHistogramAggregation

            # Example view (this can be expanded based on needs)
            histogram_view = View(
                instrument_type="histogram",
                aggregation=ExplicitBucketHistogramAggregation([
                    0, 10, 50, 100, 500, 1000, 2000
                ]),
            )

            try:
                if config.collector_endpoint or use_http:

                    exporter_kwargs = {
                        "headers": config.headers or {},
                        "compression": "gzip",
                        "timeout": 10_000,
                    }

                    if use_http:
                        metric_exporter = HTTPMetricExporter(**exporter_kwargs)
                    else:
                        metric_exporter = GRPCMetricExporter(
                            endpoint=config.collector_endpoint,
                            insecure=config.insecure,
                            **exporter_kwargs,
                        )
                else:
                    metric_exporter = ConsoleMetricExporter()

            except Exception as e:
                logger.warning("OTLPMetricExporter failed, console fallback used: %s", e)
                metric_exporter = ConsoleMetricExporter()

            metric_reader = PeriodicExportingMetricReader(
                metric_exporter,
                export_interval_millis=config.export_interval_ms,
            )

            meter_provider = MeterProvider(
                resource=resource,
                metric_readers=[metric_reader],
                views=[histogram_view],
            )

            metrics.set_meter_provider(meter_provider)
            providers["meter_provider"] = meter_provider

        except Exception as e:
            logger.debug("Metrics setup failed: %s", e)

        # ================================
        # 4️ LOGS — handled in LogsManager
        # ================================
        providers["logger_provider"] = None

    except Exception as e:
        logger.exception("Failed setting up OTEL: %s", e)

    return providers




f"""setup_otel() initializes OpenTelemetry Tracing + Metrics for your SDK:

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