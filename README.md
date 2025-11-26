📦 Sify Telemetry SDK

A lightweight, production-ready telemetry SDK for Traces, Metrics, Logs & Auto-Instrumentation.

This SDK provides a simple, unified interface for sending observability data (traces, metrics, logs) to an OpenTelemetry Collector, with support for both manual instrumentation and auto-instrumentation.

🚀 Features

🔹 Tracing (Distributed Traces)

Start spans

Add attributes, events

Record exceptions

Automatic context propagation



🔹 Metrics

Counters

UpDownCounters

Histograms

Observable metrics (Gauge, Counter, UpDownCounter)


🔹 Logs

Structured logs

Error logging

Auto-correlation with traces

Sensitive data masking



🤖 Auto-Instrumentation

Libraries: requests, httpx, urllib3, sqlalchemy, redis, flask, fastapi, django
Class-level, method-level, decorator-based instrumentation


AUTO_INSTRUMENTATION_GUIDE

🏗 Architecture
Your Application
     ↓ (calls)
Sify Telemetry SDK
     ↓ (OTLP)
OpenTelemetry Collector
     ↓
Backends: Jaeger, Tempo, Prometheus, Grafana, Loki

** 📥 Installation **


pip install git+https://github.com/your/repo.git

With auto-instrumentation dependencies
pip install sify-telemetry-sdk[auto]

The SDK supports multiple installation modes depending on how much functionality you need.

🔹 1. Core Installation (Minimal – Default)

Installs only the core telemetry engine (traces, metrics, logs).

pip install sify-telemetry-sdk

🔸 2. With Exporters (Send data to OTEL Collector)

Installs OTLP gRPC/HTTP exporters.

pip install sify-telemetry-sdk[exporters]

🔹 3. With Auto-Instrumentation (requests, FastAPI, Flask, etc.)
pip install sify-telemetry-sdk[auto]

🔸 4. Full Installation (Everything Enabled)

Core + exporters + all instrumentation.

pip install sify-telemetry-sdk[exporters,auto]


After installation please conform with:

from telemetry import TelemetryCollector, TelemetryConfig
print("SDK imported successfully!")
