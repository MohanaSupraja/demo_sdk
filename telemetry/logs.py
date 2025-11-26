import logging
from typing import Dict, Any
from enum import Enum

# Correct imports for OTel 1.19.0
from opentelemetry._logs import SeverityNumber
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


class LogsManager:
    """
    Logs via OpenTelemetry (if available) or Python logging fallback.

    Adds:
    - sensitive field masking
    - trace_id/span_id correlation
    """

    def __init__(self, config: TelemetryConfig):
        self.config = config

        try:
            # ------------------------------
            # Choose HTTP vs console
            # ------------------------------
            use_http = (config.protocol or "").startswith("http")

            # OTel Logger Provider
            self.otel_logger_provider = LoggerProvider()

            # ------------------------------
            # Select OTLP Log Exporter
            # ------------------------------
            try:
                if config.enable_logs and (config.collector_endpoint or use_http):

                    if use_http:
                        # 🔥 OTLP HTTP LOG EXPORTER
                        from opentelemetry.exporter.otlp.proto.http._log_exporter import (
                            OTLPLogExporter,
                        )

                        log_exporter = OTLPLogExporter(
                            headers=config.headers or {},
                        )

                    else:
                        # 🔥 (Optional) gRPC exporter (not used since you want HTTP)
                        from opentelemetry.exporter.otlp.proto.grpc._log_exporter import (
                            OTLPLogExporter,
                        )

                        log_exporter = OTLPLogExporter(
                            endpoint=config.collector_endpoint,
                            insecure=config.insecure,
                            headers=config.headers or {},
                        )
                else:
                    # No collector configured → console only
                    log_exporter = ConsoleLogExporter()

            except Exception as e:
                logging.getLogger(__name__).warning(
                    "OTLPLogExporter failed, falling back to console: %s", e
                )
                log_exporter = ConsoleLogExporter()

            # Install exporter
            self.otel_logger_provider.add_log_record_processor(
                BatchLogRecordProcessor(log_exporter)
            )

            # Create Logger instance
            self.otel_logger = self.otel_logger_provider.get_logger(
                config.service_name or "default"
            )

        except Exception:
            self.otel_logger_provider = None
            self.otel_logger = None

        # fallback Python logger
        self.python_logger = logging.getLogger(config.service_name or __name__)

    # --------------------------------------------------------
    # Helpers
    # --------------------------------------------------------
    def _get_trace_context(self):
        """Add trace_id & span_id to logs."""
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

    def _mask(self, attributes: Dict[str, Any]):
        """Mask sensitive data."""
        return mask_sensitive(attributes or {}, self.config.sensitive_fields or [])

    # --------------------------------------------------------
    # Main log method
    # --------------------------------------------------------
    def log(self, level: LogLevel, message: str, attributes: Dict[str, Any] = None):
        attributes = self._mask(attributes or {})
        attributes.update(self._get_trace_context())

        severity = {
            LogLevel.DEBUG: SeverityNumber.DEBUG,
            LogLevel.INFO: SeverityNumber.INFO,
            LogLevel.WARNING: SeverityNumber.WARN,
            LogLevel.ERROR: SeverityNumber.ERROR,
            LogLevel.CRITICAL: SeverityNumber.FATAL,
        }[level]

        # Try OpenTelemetry log path
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

        # Fallback Python logging
        getattr(self.python_logger, level.value.lower())(
            message, extra={"otel": attributes}
        )

    # --------------------------------------------------------
    # Convenience wrappers
    # --------------------------------------------------------
    def debug(self, msg, attributes=None):
        self.log(LogLevel.DEBUG, msg, attributes)

    def info(self, msg, attributes=None):
        self.log(LogLevel.INFO, msg, attributes)

    def warning(self, msg, attributes=None):
        self.log(LogLevel.WARNING, msg, attributes)

    def error(self, msg, attributes=None):
        self.log(LogLevel.ERROR, msg, attributes)

    def critical(self, msg, attributes=None):
        self.log(LogLevel.CRITICAL, msg, attributes)

    def flush(self, timeout_seconds: float = 5.0) -> None:
        """
        Flush pending logs. Safe no-op if logging backend not configured.
        """
        try:
            if self.otel_logger_provider is not None:
                if hasattr(self.otel_logger_provider, "force_flush"):
                    try:
                        self.otel_logger_provider.force_flush(timeout_seconds)
                    except TypeError:
                        self.otel_logger_provider.force_flush()

                if hasattr(self.otel_logger_provider, "shutdown"):
                    try:
                        self.otel_logger_provider.shutdown()
                    except TypeError:
                        self.otel_logger_provider.shutdown()
        except Exception as e:
            logging.getLogger(__name__).debug(
                "LogsManager.flush: OTel flush/shutdown failed: %s", e, exc_info=True
            )

        # Flush Python fallback
        try:
            py_logger = self.python_logger
            for handler in getattr(py_logger, "handlers", []):
                try:
                    if hasattr(handler, "flush"):
                        handler.flush()
                except Exception:
                    logging.getLogger(__name__).debug(
                        "LogsManager.flush: handler.flush() failed",
                        exc_info=True,
                    )
        except Exception as e:
            logging.getLogger(__name__).debug(
                "LogsManager.flush: Python logger flush failed: %s", e, exc_info=True
            )
