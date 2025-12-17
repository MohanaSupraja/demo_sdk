from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional
import os


@dataclass
class TelemetryConfig:
    """
    Central configuration object for the entire Observability SDK.
    Handles both manual + auto-instrumentation cleanly.
    """

    # -------------------------------------------------------------
    # SERVICE METADATA
    # -------------------------------------------------------------
    service_name: str = "sify-service"
    resource_attributes: Dict[str, str] = field(default_factory=dict)

    # -------------------------------------------------------------
    # OTLP EXPORTER SETTINGS
    # -------------------------------------------------------------
    collector_endpoint: Optional[str] = None
    protocol: str = "http/protobuf"         # {"http/protobuf", "grpc"}
    headers: Dict[str, str] = field(default_factory=dict)
    insecure: bool = True                    # Only for gRPC

   
    # FEATURE FLAGS
    enable_traces: bool = False
    enable_metrics: bool = False
    enable_logs: bool = False

    # AUTO-INSTRUMENTATION CONTROL
    auto_instrument: bool = False


    # Framework (Flask, FastAPI, Django)
    instrument_frameworks: bool = True
    framework_app: Any = None

    # Library instrumentation (requests, urllib3, httpx)
    instrument_libraries_enabled: bool = True
    instrument_libraries: List[str] = field(
        default_factory=lambda: ["requests", "urllib3", "httpx"]
    )

    # Database instrumentation
    instrument_databases_enabled: bool = False
    instrument_databases: List[str] = field(
        default_factory=lambda: ["sqlalchemy"]
    )

    # Instrument this SDK itself
    instrument_sify_sdk: bool = False

    # -------------------------------------------------------------
    # SAMPLING + BATCH EXPORT SETTINGS
    # -------------------------------------------------------------
    sampling_rate: float = 1.0
    export_interval_ms: int = 5000
    max_queue_size: int = 2048
    max_export_batch_size: int = 512

    # -------------------------------------------------------------
    # HTTP CAPTURE SETTINGS
    # -------------------------------------------------------------
    capture_headers: bool = False
    capture_query_params: bool = True
    capture_request_body: bool = False
    capture_response_body: bool = False
    capture_sql_queries: bool = True

    log_sample_rate: float = 1.0

    # -------------------------------------------------------------
    # DATA MASKING
    # -------------------------------------------------------------
    mask_sensitive_data: bool = True
    sensitive_fields: List[str] = field(
        default_factory=lambda: ["password", "api_key", "token", "secret"]
    )
    exclude_urls: List[str] = field(default_factory=lambda: ["/health", "/metrics"])
    max_span_attributes: int = 100


    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    # LOAD FROM ENVIRONMENT
    
    # @staticmethod
    # def from_env() -> "TelemetryConfig":

    #     def get_bool(name: str, default=False):
    #         v = os.environ.get(name)
    #         if v is None:
    #             return default
    #         return v.lower() in ("1", "true", "yes", "on")

    #     raw_endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    #     raw_protocol = os.environ.get("OTEL_EXPORTER_OTLP_PROTOCOL", "http/protobuf")

    #     cfg = TelemetryConfig(
    #         service_name=os.environ.get("OTEL_SERVICE_NAME", "sify-service"),

    #         collector_endpoint=raw_endpoint,
    #         protocol=raw_protocol.lower(),

    #         enable_traces=get_bool("SIFY_ENABLE_TRACES", True),
    #         enable_metrics=get_bool("SIFY_ENABLE_METRICS", True),
    #         enable_logs=get_bool("SIFY_ENABLE_LOGS", True),

    #         auto_instrument=get_bool("SIFY_AUTO_INSTRUMENT", False),

    #         instrument_frameworks=get_bool("SIFY_INSTRUMENT_FRAMEWORKS", True),

    #         instrument_libraries_enabled=get_bool("SIFY_INSTRUMENT_LIBRARIES_ENABLED", True),
    #         instrument_databases_enabled=get_bool("SIFY_INSTRUMENT_DATABASES_ENABLED", True),

    #         instrument_libraries=(
    #             os.environ.get("SIFY_INSTRUMENT_LIBRARIES", "").split(",")
    #             if os.environ.get("SIFY_INSTRUMENT_LIBRARIES")
    #             else ["requests", "urllib3", "httpx"]
    #         ),

    #         instrument_databases=(
    #             os.environ.get("SIFY_INSTRUMENT_DATABASES", "").split(",")
    #             if os.environ.get("SIFY_INSTRUMENT_DATABASES")
    #             else ["sqlalchemy", "psycopg2", "pymysql", "redis", "pymongo"]
    #         ),

    #         instrument_sify_sdk=get_bool("SIFY_INSTRUMENT_SDK", False),

    #         sampling_rate=float(os.environ.get("SIFY_SAMPLING_RATE", "1.0")),
    #         export_interval_ms=int(os.environ.get("SIFY_EXPORT_INTERVAL_MS", "5000")),
    #         log_sample_rate=float(os.environ.get("SIFY_LOG_SAMPLE_RATE", "1.0")),
    #     )

    #     # Normalize HTTP endpoint
    #     if cfg.collector_endpoint and cfg.protocol.startswith("http"):
    #         REMOVE_SUFFIXES = [
    #             "/v1/traces", "/v1/metrics", "/v1/logs",
    #             "/v1/traces/", "/v1/metrics/", "/v1/logs/"
    #         ]
    #         for suf in REMOVE_SUFFIXES:
    #             if cfg.collector_endpoint.endswith(suf):
    #                 cfg.collector_endpoint = cfg.collector_endpoint[:-len(suf)]
    #                 break

    #         cfg.collector_endpoint = cfg.collector_endpoint.rstrip("/")

    #     # Always attach service name to resources
    #     cfg.resource_attributes["service.name"] = cfg.service_name

    #     return cfg




# ---------------resource_attributes means

# service name

# environment (dev/test/prod)

# region

# host name

# container ID

# version