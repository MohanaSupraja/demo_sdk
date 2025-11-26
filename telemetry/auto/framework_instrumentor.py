
import logging
from typing import Any

logger = logging.getLogger(__name__)

class FrameworkInstrumentor:
    """
    Framework-specific instrumentation helpers.
    These often require an app object (Flask, FastAPI, Django).
    """

    def __init__(self):
        self._instrumented_apps = {}  # app id -> framework name

    def instrument_app(self, app: Any, framework: str = None) -> bool:
        """
        Instrument a framework app instance.
        - framework: optional override like 'flask' or 'starlette'
        Returns True on success.
        """
        # Best-effort: detect framework by attributes if not provided
        try:
            if framework is None:
                # naive detection
                if hasattr(app, "wsgi_app") and hasattr(app, "route"):
                    framework = "flask"
                elif hasattr(app, "router") and hasattr(app, "add_event_handler"):
                    framework = "fastapi"  # starlette-ish
                else:
                    logger.debug("Could not detect framework for app; pass framework explicitly.")
                    return False

            framework = framework.lower()
            if framework == "flask":
                try:
                    from opentelemetry.instrumentation.flask import FlaskInstrumentor
                    FlaskInstrumentor().instrument_app(app)
                    self._instrumented_apps[id(app)] = "flask"
                    logger.info("Instrumented Flask app")
                    return True
                except Exception as e:
                    logger.debug("Flask instrumentation failed: %s", e, exc_info=True)
                    return False

            if framework in ("fastapi", "starlette"):
                try:
                    # FastAPI uses the ASGI instrumentor (Starlette)
                    from opentelemetry.instrumentation.asgi import OpenTelemetryMiddleware
                    # For FastAPI, insert middleware if not already present
                    if not any(m.__class__.__name__ == "OpenTelemetryMiddleware" for m in getattr(app, "user_middleware", [])):
                        app.add_middleware(OpenTelemetryMiddleware)
                    self._instrumented_apps[id(app)] = "fastapi"
                    logger.info("Instrumented FastAPI/Starlette app (added ASGI middleware)")
                    return True
                except Exception as e:
                    logger.debug("FastAPI/Starlette instrumentation failed: %s", e, exc_info=True)
                    return False

            # add other frameworks (Django, Tornado) as needed
            logger.debug("Framework %s not supported by instrument_app", framework)
            return False
        except Exception as e:
            logger.debug("instrument_app encountered error: %s", e, exc_info=True)
            return False

    def uninstrument_app(self, app: Any) -> bool:
        """
        Attempt to remove instrumentation for an app (best-effort).
        Many frameworks do not support dynamic uninstrumentation.
        """
        try:
            fid = id(app)
            frm = self._instrumented_apps.get(fid)
            if not frm:
                return False

            if frm == "flask":
                # FlaskInstrumentor has uninstrument_app in some versions
                try:
                    from opentelemetry.instrumentation.flask import FlaskInstrumentor
                    FlaskInstrumentor().uninstrument_app(app)
                    self._instrumented_apps.pop(fid, None)
                    logger.info("Uninstrumented Flask app")
                    return True
                except Exception:
                    # best-effort fallback
                    logger.debug("Flask uninstrumentation failed", exc_info=True)
                    return False

            if frm == "fastapi":
                # Removing middleware dynamically is tricky; skip
                logger.debug("Dynamic uninstrumentation for FastAPI is unsupported or unsafe")
                return False

            return False
        except Exception as e:
            logger.debug("uninstrument_app error: %s", e, exc_info=True)
            return False
