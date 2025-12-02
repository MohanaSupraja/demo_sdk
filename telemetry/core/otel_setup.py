import logging
from typing import Dict, Any
from ..config import TelemetryConfig

logger = logging.getLogger(__name__)


def setup_otel(config: TelemetryConfig) -> Dict[str, Any]:
    """
    Production-grade OpenTelemetry initialization.
    Handles:
      - Traces (HTTP / gRPC / Console fallback)
      - Metrics (HTTP / gRPC / Console fallback)
      - Logs (HTTP / gRPC / Console fallback)  ← FIXED
    """

    providers = {
        "tracer_provider": None,
        "meter_provider": None,
        "logger_provider": None,
    }

    try:
        # ------------------------------------------------------------
        # Imports
        # ------------------------------------------------------------
        from opentelemetry.sdk.resources import Resource
        from opentelemetry import trace, metrics

        from opentelemetry.sdk.trace import TracerProvider, SpanLimits
        from opentelemetry.sdk.trace.export import (
            BatchSpanProcessor,
            ConsoleSpanExporter,
        )

        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import (
            PeriodicExportingMetricReader,
            ConsoleMetricExporter,
        )

        # OTLP Exporters
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter as HTTPTraceExporter
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter as HTTPMetricExporter
        from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter as HTTPLogExporter

        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter as GRPCTraceExporter
        from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter as GRPCMetricExporter
        from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter as GRPCLogExporter

        # Logs backend
        from opentelemetry.sdk._logs import LoggerProvider
        from opentelemetry._logs import set_logger_provider
        from opentelemetry.sdk._logs.export import (
            BatchLogRecordProcessor,
            ConsoleLogExporter,
        )

        # ------------------------------------------------------------
        # Build Resource
        # ------------------------------------------------------------
        resource_attrs = config.resource_attributes or {}
        resource_attrs["service.name"] = config.service_name

        resource = Resource(attributes=resource_attrs)
        use_http = (config.protocol or "").lower().startswith("http")

        # ------------------------------------------------------------
        # TRACE PROVIDER
        # ------------------------------------------------------------
        try:
            span_limits = SpanLimits(
                max_attributes=config.max_span_attributes,
                max_events=256,
                max_links=128,
            )

            tracer_provider = TracerProvider(
                resource=resource,
                span_limits=span_limits
            )

            # exporter selection
            try:
                if use_http and config.collector_endpoint:
                    span_exporter = HTTPTraceExporter(
                        endpoint=f"{config.collector_endpoint}/v1/traces",
                        headers=config.headers or {},
                    )
                elif config.collector_endpoint:
                    span_exporter = GRPCTraceExporter(
                        endpoint=config.collector_endpoint,
                        insecure=config.insecure,
                        headers=config.headers or {},
                    )
                else:
                    span_exporter = ConsoleSpanExporter()

            except Exception as e:
                logger.warning("HTTP/GRPC trace exporter failed → console fallback: %s", e)
                span_exporter = ConsoleSpanExporter()

            processor = BatchSpanProcessor(
                span_exporter,
                max_export_batch_size=config.max_export_batch_size,
                max_queue_size=config.max_queue_size,
                schedule_delay_millis=config.export_interval_ms,
            )

            tracer_provider.add_span_processor(processor)

            from opentelemetry.trace import get_tracer_provider, TracerProvider as SDKTracerProvider
            current = get_tracer_provider()

            if not isinstance(current, SDKTracerProvider):
                trace.set_tracer_provider(tracer_provider)

            providers["tracer_provider"] = tracer_provider

        except Exception as e:
            logger.error("Error setting up TracerProvider: %s", e, exc_info=True)

        # ------------------------------------------------------------
        # METRICS PROVIDER
        # ------------------------------------------------------------
        try:
            try:
                if use_http and config.collector_endpoint:
                    metric_exporter = HTTPMetricExporter(
                        endpoint=f"{config.collector_endpoint}/v1/metrics",
                        headers=config.headers or {},
                    )
                elif config.collector_endpoint:
                    metric_exporter = GRPCMetricExporter(
                        endpoint=config.collector_endpoint,
                        insecure=config.insecure,
                        headers=config.headers or {},
                    )
                else:
                    metric_exporter = ConsoleMetricExporter()

            except Exception as e:
                logger.warning("Metric exporter failed → console: %s", e)
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

        # ------------------------------------------------------------
        # LOG PROVIDER (FIXED)
        # ------------------------------------------------------------
        try:
            logger_provider = LoggerProvider(resource=resource)

            # export via HTTP or gRPC
            try:
                if use_http and config.collector_endpoint:
                    log_exporter = HTTPLogExporter(
                        endpoint=f"{config.collector_endpoint}/v1/logs",
                        headers=config.headers or {},
                    )
                elif config.collector_endpoint:
                    log_exporter = GRPCLogExporter(
                        endpoint=config.collector_endpoint,
                        insecure=config.insecure,
                        headers=config.headers or {},
                    )
                else:
                    log_exporter = ConsoleLogExporter()

            except Exception as e:
                logger.warning("Log exporter failed → console: %s", e)
                log_exporter = ConsoleLogExporter()

            logger_provider.add_log_record_processor(
                BatchLogRecordProcessor(log_exporter)
            )

            # REGISTER GLOBALLY  ← REQUIRED for logs to work
            set_logger_provider(logger_provider)

            providers["logger_provider"] = logger_provider

        except Exception as e:
            logger.error("Logs setup failed: %s", e)

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