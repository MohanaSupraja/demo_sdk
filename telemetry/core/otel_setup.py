import logging
from typing import Dict, Any
from ..config import TelemetryConfig

logger = logging.getLogger(__name__)


def setup_otel(config: TelemetryConfig) -> Dict[str, Any]:
    """
    Setup OpenTelemetry Traces + Metrics.
    (Logs are handled separately in LogsManager)
    """
    providers = {
        "tracer_provider": None,
        "meter_provider": None,
        "logger_provider": None   # We do NOT configure logs here
    }

    try:
        from opentelemetry.sdk.resources import Resource
        from opentelemetry import trace, metrics

        # Build resource
        resource_attrs = config.resource_attributes or {}
        resource_attrs["service.name"] = config.service_name
        resource = Resource(attributes=resource_attrs)

        # Decide protocol
        use_http = (config.protocol or "").startswith("http")

        # ------------------------------------------------------------------
        # TRACES
        # ------------------------------------------------------------------
        try:
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import (
                BatchSpanProcessor,
                ConsoleSpanExporter,
            )

            tracer_provider = TracerProvider(resource=resource)

            # Exporter selection
            try:
                if config.collector_endpoint or use_http:

                    if use_http:
                        # 🔥 OTLP HTTP TRACE EXPORTER
                        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                            OTLPSpanExporter,
                        )

                        # HTTP exporters derive /v1/traces automatically from endpoint env var
                        span_exporter = OTLPSpanExporter(
                            headers=config.headers or {},
                        )

                    else:
                        # 🔥 OTLP gRPC TRACE EXPORTER (existing behavior)
                        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                            OTLPSpanExporter,
                        )

                        span_exporter = OTLPSpanExporter(
                            endpoint=config.collector_endpoint,
                            insecure=config.insecure,
                            headers=config.headers or {},
                        )
                else:
                    span_exporter = ConsoleSpanExporter()

            except Exception as e:
                logger.warning("OTLPSpanExporter failed, falling back to console: %s", e)
                span_exporter = ConsoleSpanExporter()

            tracer_provider.add_span_processor(
                BatchSpanProcessor(span_exporter)
            )

            trace.set_tracer_provider(tracer_provider)
            providers["tracer_provider"] = tracer_provider

        except Exception as e:
            logger.debug("Tracer setup failed: %s", e)

        # ------------------------------------------------------------------
        # METRICS
        # ------------------------------------------------------------------
        try:
            from opentelemetry.sdk.metrics import MeterProvider
            from opentelemetry.sdk.metrics.export import (
                ConsoleMetricExporter,
                PeriodicExportingMetricReader,
            )

            try:
                if config.collector_endpoint or use_http:

                    if use_http:
                        # 🔥 OTLP HTTP METRIC EXPORTER
                        from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
                            OTLPMetricExporter,
                        )

                        metric_exporter = OTLPMetricExporter(
                            headers=config.headers or {},
                        )

                    else:
                        # 🔥 OTLP gRPC METRICS EXPORTER (your existing behavior)
                        from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import (
                            OTLPMetricExporter,
                        )

                        metric_exporter = OTLPMetricExporter(
                            endpoint=config.collector_endpoint,
                            insecure=config.insecure,
                            headers=config.headers or {},
                        )
                else:
                    metric_exporter = ConsoleMetricExporter()

            except Exception as e:
                logger.warning("OTLPMetricExporter failed, falling back to console: %s", e)
                metric_exporter = ConsoleMetricExporter()

            # Periodic exporting
            metric_reader = PeriodicExportingMetricReader(
                metric_exporter
            )

            meter_provider = MeterProvider(
                resource=resource,
                metric_readers=[metric_reader],
            )

            metrics.set_meter_provider(meter_provider)
            providers["meter_provider"] = meter_provider

        except Exception as e:
            logger.debug("Metrics setup failed: %s", e)

        # ------------------------------------------------------------------
        # LOGS
        # ------------------------------------------------------------------
        # LogsManager handles logging — OTEL logs API is unstable in v1.19.
        providers["logger_provider"] = None

    except Exception as e:
        logger.exception("Failed setting up OTEL: %s", e)

    return providers
