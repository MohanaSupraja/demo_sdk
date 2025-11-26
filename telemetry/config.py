from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional
import os


@dataclass
class TelemetryConfig:
    service_name: str = "sify-service"

    # Default OTLP/HTTP endpoint structure (collector host only)
    collector_endpoint: Optional[str] = None

    # Default protocol is now HTTP
    # valid values: "http/protobuf", "grpc"
    protocol: str = "http/protobuf"

    # Enable instrumentation
    enable_traces: bool = True
    enable_metrics: bool = True
    enable_logs: bool = True

    auto_instrument: bool = False
    instrument_libraries: List[str] = field(
        default_factory=lambda: ["requests", "urllib3", "httpx"]
    )
    framework_app: Any = None
    instrument_frameworks: bool = True

    instrument_sify_sdk: bool = False

    # Sampling + batch export
    sampling_rate: float = 1.0
    export_interval_ms: int = 5000
    max_queue_size: int = 2048
    max_export_batch_size: int = 512

    # Headers for HTTP exporters
    headers: Dict[str, str] = field(default_factory=dict)

    # Resource attributes
    resource_attributes: Dict[str, str] = field(default_factory=dict)

    insecure: bool = True  # for grpc only

    # HTTP capture controls
    capture_headers: bool = False
    capture_query_params: bool = True
    capture_request_body: bool = False
    capture_response_body: bool = False
    capture_sql_queries: bool = True

    # Sensitive data masking
    mask_sensitive_data: bool = True
    sensitive_fields: List[str] = field(
        default_factory=lambda: ["password", "api_key", "token"]
    )
    exclude_urls: List[str] = field(default_factory=lambda: ["/health", "/metrics"])
    max_span_attributes: int = 100

    # ---------------------------------------------------------
    # Convert config to dict
    # ---------------------------------------------------------
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    # ---------------------------------------------------------
    # Build from environment variables
    # ---------------------------------------------------------
    @staticmethod
    def from_env() -> "TelemetryConfig":
        def get_bool(name, default=False):
            v = os.environ.get(name)
            if v is None:
                return default
            return v.lower() in ("1", "true", "yes", "on")

        # Read raw endpoint + protocol
        raw_endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
        raw_protocol = os.environ.get("OTEL_EXPORTER_OTLP_PROTOCOL", "http/protobuf").lower()

        cfg = TelemetryConfig(
            service_name=os.environ.get("OTEL_SERVICE_NAME", "sify-service"),

            collector_endpoint=raw_endpoint,
            protocol=raw_protocol,

            enable_traces=get_bool("SIFY_ENABLE_TRACES", True),
            enable_metrics=get_bool("SIFY_ENABLE_METRICS", True),
            enable_logs=get_bool("SIFY_ENABLE_LOGS", True),

            auto_instrument=get_bool("SIFY_AUTO_INSTRUMENT", False),

            instrument_libraries=(
                (os.environ.get("SIFY_INSTRUMENT_LIBRARIES") or "").split(",")
                if os.environ.get("SIFY_INSTRUMENT_LIBRARIES")
                else ["requests", "urllib3", "httpx"]
            ),

            instrument_frameworks=get_bool("SIFY_INSTRUMENT_FRAMEWORKS", False),
            instrument_sify_sdk=get_bool("SIFY_INSTRUMENT_SDK", False),

            sampling_rate=float(os.environ.get("SIFY_SAMPLING_RATE", "1.0")),
            export_interval_ms=int(os.environ.get("SIFY_EXPORT_INTERVAL_MS", "5000")),
        )

        # ---------------------------------------------------------
        # Normalize HTTP OTLP endpoint
        # ---------------------------------------------------------
        if cfg.collector_endpoint and cfg.protocol.startswith("http"):

            # Remove paths incorrectly added by user
            REMOVE_SUFFIXES = [
                "/v1/traces",
                "/v1/metrics",
                "/v1/logs",
                "/v1/traces/",
                "/v1/metrics/",
                "/v1/logs/",
            ]

            for suf in REMOVE_SUFFIXES:
                if cfg.collector_endpoint.endswith(suf):
                    cfg.collector_endpoint = cfg.collector_endpoint[: -len(suf)]
                    break

            # Remove trailing slash → exporters add /v1/traces automatically
            cfg.collector_endpoint = cfg.collector_endpoint.rstrip("/")

        return cfg
