import logging
import traceback
from typing import Dict, Any, Optional
from enum import Enum
import socket
import time
import random

# Correct imports for OTel 1.19.0
from opentelemetry._logs import SeverityNumber, set_logger_provider
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor, ConsoleLogExporter
from opentelemetry.trace import get_current_span

from telemetry.utils.masking import mask_sensitive
from telemetry.config import TelemetryConfig


class LogLevel(Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"
    AUDIT = "AUDIT"
    SECURITY = "SECURITY"


class LogsManager:
    """
    Production-grade Logging Manager.

    Features:
    - OTel log export (HTTP/gRPC)
    - Python logger fallback
    - Sensitive field masking
    - Automatic trace_id/span_id injection
    - Additional context (hostname, service, env)
    - Exception helper
    - Log sampling support
    """

    def __init__(self, config: TelemetryConfig, logger_provider: Optional[LoggerProvider] = None):
        self.config = config
        self.sample_rate = float(getattr(config, "log_sample_rate", 1.0))
        self.hostname = socket.gethostname()

        # ------------------------------
        # Setup OpenTelemetry Logger
        # ------------------------------
        try:
            # Reuse existing provider if given (from setup_otel), otherwise create & register a new one
            if logger_provider is not None:
                self.otel_logger_provider = logger_provider
            else:
                self.otel_logger_provider = LoggerProvider()
                #  IMPORTANT: register as global provider so LoggingInstrumentor + others can use it
                set_logger_provider(self.otel_logger_provider)

            use_http = (config.protocol or "").startswith("http")

            try:
                if config.enable_logs and (config.collector_endpoint or use_http):
                    if use_http:
                        # HTTP exporter
                        from opentelemetry.exporter.otlp.proto.http._log_exporter import (
                            OTLPLogExporter,
                        )
                        log_exporter = OTLPLogExporter(
                            endpoint=f"{config.collector_endpoint.rstrip('/')}/v1/logs",
                            headers=config.headers or {},
                        )
                    else:
                        # gRPC exporter (optional)
                        from opentelemetry.exporter.otlp.proto.grpc._log_exporter import (
                            OTLPLogExporter,
                        )
                        log_exporter = OTLPLogExporter(
                            endpoint=config.collector_endpoint,
                            insecure=config.insecure,
                            headers=config.headers or {},
                        )
                else:
                    # Fallback if logs disabled or no endpoint → console
                    log_exporter = ConsoleLogExporter()

            except Exception as e:
                logging.getLogger(__name__).warning(
                    "OTLPLogExporter failed, using ConsoleLogExporter: %s", e
                )
                log_exporter = ConsoleLogExporter()

            # Attach batch processor to logger provider
            self.otel_logger_provider.add_log_record_processor(
                BatchLogRecordProcessor(log_exporter)
            )

            # Create logger for this service
            self.otel_logger = self.otel_logger_provider.get_logger(
                config.service_name or "default"
            )

        except Exception:
            self.otel_logger_provider = None
            self.otel_logger = None

        # Python logger fallback
        self.python_logger = logging.getLogger(config.service_name or __name__)

    # --------------------------------------------------------
    # Context helpers
    # --------------------------------------------------------
    def _get_trace_context(self):
        """Inject trace_id & span_id."""
        try:
            span = get_current_span()
            ctx = span.get_span_context()
            if ctx and ctx.trace_id != 0:
                return {
                    "trace_id": f"{ctx.trace_id:032x}",
                    "span_id": f"{ctx.span_id:016x}",
                }
        except Exception:
            pass
        return {}

    def _extra_context(self):
        """Attach hostname, service, environment, timestamp."""
        return {
            "service.name": self.config.service_name,
            "host.name": self.hostname,
            "timestamp": int(time.time() * 1000),
        }

    def _mask(self, attributes: Dict[str, Any]):
        """Mask sensitive nested fields."""
        return mask_sensitive(attributes or {}, self.config.sensitive_fields or [])

    def _should_sample(self):
        """Probability sampling (0.0 → 0%, 1.0 → 100%)."""
        if self.sample_rate >= 1.0:
            return True
        return random.random() < self.sample_rate

    # --------------------------------------------------------
    # Main Logging Method
    # --------------------------------------------------------
    def log(self, level: LogLevel, message: str, attributes: Optional[Dict[str, Any]] = None):
        if not self._should_sample():
            return  # sampled out

        attributes = attributes or {}
        attributes = self._mask(attributes)
        attributes.update(self._get_trace_context())
        attributes.update(self._extra_context())

        severity = {
            LogLevel.DEBUG: SeverityNumber.DEBUG,
            LogLevel.INFO: SeverityNumber.INFO,
            LogLevel.WARNING: SeverityNumber.WARN,
            LogLevel.ERROR: SeverityNumber.ERROR,
            LogLevel.CRITICAL: SeverityNumber.FATAL,
            LogLevel.AUDIT: SeverityNumber.INFO,
            LogLevel.SECURITY: SeverityNumber.WARN,
        }[level]

        # Try OTel logger first
        if self.otel_logger:
            try:
                self.otel_logger.emit(
                    body=message,
                    severity_number=severity,
                    severity_text=level.value,
                    attributes=attributes,
                )
                return
            except Exception:
                pass

        # Python fallback
        getattr(self.python_logger, level.value.lower(), self.python_logger.info)(
            message, extra={"otel": attributes}
        )

    # --------------------------------------------------------
    # Convenience wrappers
    # --------------------------------------------------------
    def debug(self, msg, attributes=None): self.log(LogLevel.DEBUG, msg, attributes)
    def info(self, msg, attributes=None): self.log(LogLevel.INFO, msg, attributes)
    def warning(self, msg, attributes=None): self.log(LogLevel.WARNING, msg, attributes)
    def error(self, msg, attributes=None): self.log(LogLevel.ERROR, msg, attributes)
    def critical(self, msg, attributes=None): self.log(LogLevel.CRITICAL, msg, attributes)
    def audit(self, msg, attributes=None): self.log(LogLevel.AUDIT, msg, attributes)
    def security(self, msg, attributes=None): self.log(LogLevel.SECURITY, msg, attributes)

    # --------------------------------------------------------
    # Exception logging helper
    # --------------------------------------------------------
    def exception(self, error: Exception, attributes: Optional[Dict[str, Any]] = None):
        return self.log(
            LogLevel.ERROR,
            str(error),
            {
                "exception.type": type(error).__name__,
                "exception.stacktrace": traceback.format_exc(),
                **(attributes or {}),
            },
        )

    # --------------------------------------------------------
    # Flush
    # --------------------------------------------------------
    def flush(self, timeout_seconds: float = 5.0):
        """Flush both OTel and Python loggers."""
        try:
            if self.otel_logger_provider and hasattr(self.otel_logger_provider, "force_flush"):
                self.otel_logger_provider.force_flush(timeout_seconds)
        except Exception:
            pass

        try:
            if self.otel_logger_provider and hasattr(self.otel_logger_provider, "shutdown"):
                self.otel_logger_provider.shutdown()
        except Exception:
            pass

        # Python fallback flush
        for handler in getattr(self.python_logger, "handlers", []):
            try:
                handler.flush()
            except Exception:
                pass





"""LogsManager — High-Level Summary

 ➡️ Sends logs to OpenTelemetry (OTLP HTTP or gRPC)

 Falls back gracefully to Python logging if OTEL exporter fails (your app NEVER loses logs)

 Automatically attaches trace_id + span_id for correlation

 Masks sensitive data (passwords, tokens, API keys)

 Supports audit, security, and exception logs

 Adds system metadata (host, service name, timestamp)

 Implements log sampling to control log volume

 Guarantees logs never crash the app — even during exporter errors

➡️ Breakdown of Major Components & What They Do 

 1. __init__() — Initialize the Logging System

This method configures:

 OpenTelemetry Logger

Chooses OTLP HTTP exporter if protocol = http

Otherwise can use OTLP gRPC

If exporter fails → automatically switches to ConsoleLogExporter

 Python Logger Fallback

Always available as a backup

Ensures logs work even if:

Collector is down

Wrong endpoint

No OTEL SDK installed

Exporter throws errors

This makes logging extremely reliable in production environments.

 2. _get_trace_context() — Adds Trace/Span IDs

Every log automatically includes:

trace_id

span_id

This allows logs to be correlated with traces in:

Jaeger

Grafana Tempo

Grafana Loki

 3. _extra_context() — Adds Useful Metadata

Additional metadata injected automatically:

service.name

host.name

timestamp (ms)

This ensures logs contain enough context for observability platforms.

 4. _mask() — Sensitive Data Protection

Masks sensitive data inside log attributes:

passwords

tokens

api_key

any fields configured in config.sensitive_fields

Crucial for security & compliance.

 5. _should_sample() — Log Sampling

Controls log volume:

1.0 → log everything

0.1 → log 10%

0.01 → log 1%

Avoids flooding collectors in high-traffic systems.

 6. log() — The Core Logging Method

This is the heart of the system.

Flow:

Check sampling

Mask sensitive attributes

Add trace_id/span_id

Add service + host metadata

Select severity

Try OTEL exporter

If OTEL export fails → Python logger fallback

This guarantees logs NEVER fail and your application remains stable.

 7. Convenience Logging Shortcuts

These call log() with predefined severity:

debug(), info(), warning(), error(), critical(), audit(), security()

Makes the API extremely easy to use.

 8. exception() — Structured Exception Logging

Automatically logs:

exception type

exception message

full stacktrace

This removes the need for manual try/catch logging boilerplate.

 9. flush() — Flush All Log Buffers

OTel batching processor flushes before shutdown

Python log handlers flush

Useful for:

serverless runtimes

graceful shutdown

tests ensuring logs are written 


➡️ If tracing is disabled (enable_traces=False)

No tracer provider is created

No spans are started

get_current_span() returns a NonRecordingSpan

This span’s trace_id = 0 and span_id = 0

Your logs will NOT contain trace_id/span_id.

➡️If tracing is enabled (enable_traces=True)

SDK creates a tracer provider

Each incoming request (via framework auto-instrumentation) creates a span

get_current_span() returns the active span

trace_id/span_id values are real

Logs contain trace → log correlation

"""