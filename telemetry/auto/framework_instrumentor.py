import logging
import sys
from typing import Any

logger = logging.getLogger(__name__)


class FrameworkInstrumentor:
    """
    Framework-specific instrumentation:
    - Flask
    - FastAPI / Starlette (ASGI)
    - Django (global instrumentation)
    """

    def __init__(self):
        self._instrumented_apps = {}  # app id -> framework name

    # ---------------------------------------------------------------------
    def instrument_app(self, app: Any, framework: str = None) -> bool:
        try:

            # ============================================================
            # 1) AUTO-DETECTION
            # ============================================================
            if framework is None:

                # Flask
                if hasattr(app, "wsgi_app") and hasattr(app, "route"):
                    framework = "flask"

                # FastAPI / Starlette
                elif hasattr(app, "router") and hasattr(app, "add_event_handler"):
                    if "fastapi" in sys.modules:
                        framework = "fastapi"
                    else:
                        framework = "starlette"

                # Django (global instrumentation)
                else:
                    try:
                        import django  # noqa
                        framework = "django"
                    except ImportError:
                        logger.debug("Could not auto-detect framework.")
                        return False

            framework = framework.lower()

            # ============================================================
            # 2) FLASK
            # ============================================================
            if framework == "flask":
                try:
                    from opentelemetry.instrumentation.flask import FlaskInstrumentor

                    FlaskInstrumentor().instrument_app(app)
                    self._instrumented_apps[id(app)] = "flask"
                    logger.info("Instrumented Flask application.")
                    return True

                except Exception as e:
                    logger.debug("Flask instrumentation failed: %s", e, exc_info=True)
                    return False

            # ============================================================
            # 3) FASTAPI / STARLETTE
            # ============================================================
            if framework in ("fastapi", "starlette"):
                try:
                    from opentelemetry.instrumentation.asgi import OpenTelemetryMiddleware

                    # Safe middleware detection across multiple FastAPI versions
                    existing_middlewares = []

                    try:
                        existing_middlewares = [
                            (m.cls.__name__ if hasattr(m, "cls") else m.__class__.__name__)
                            for m in getattr(app, "user_middleware", [])
                        ]
                    except Exception:
                        pass

                    if "OpenTelemetryMiddleware" not in existing_middlewares:
                        try:
                            app.add_middleware(OpenTelemetryMiddleware)
                        except Exception:
                            logger.debug("Could not add ASGI middleware.", exc_info=True)

                    self._instrumented_apps[id(app)] = framework
                    logger.info(f"Instrumented {framework} app (ASGI middleware).")
                    return True

                except Exception as e:
                    logger.debug(f"{framework} instrumentation failed: {e}", exc_info=True)
                    return False

            # ============================================================
            # 4) DJANGO (global instrumentation)
            # ============================================================
            if framework == "django":
                try:
                    from opentelemetry.instrumentation.django import DjangoInstrumentor

                    DjangoInstrumentor().instrument()
                    self._instrumented_apps[id(app)] = "django"
                    logger.info("Instrumented Django globally.")
                    return True

                except Exception as e:
                    logger.debug("Django instrumentation failed: %s", e, exc_info=True)
                    return False

            # ============================================================
            logger.debug("Framework '%s' not supported.", framework)
            return False

        except Exception as e:
            logger.debug("instrument_app error: %s", e, exc_info=True)
            return False

    # ---------------------------------------------------------------------
    # 5) UN-INSTRUMENTATION (best-effort)
    # ---------------------------------------------------------------------
    def uninstrument_app(self, app: Any) -> bool:
        try:
            fid = id(app)
            framework = self._instrumented_apps.get(fid)

            if not framework:
                return False

            # Flask
            if framework == "flask":
                try:
                    from opentelemetry.instrumentation.flask import FlaskInstrumentor
                    FlaskInstrumentor().uninstrument_app(app)
                    self._instrumented_apps.pop(fid, None)
                    logger.info("Uninstrumented Flask app.")
                    return True
                except Exception:
                    logger.debug("Flask uninstrumentation failed.", exc_info=True)
                    return False

            # FastAPI / Starlette
            if framework in ("fastapi", "starlette"):
                logger.debug("FastAPI/Starlette runtime uninstrumentation not supported.")
                return False

            # Django
            if framework == "django":
                logger.debug("Django cannot be uninstrumented at runtime.")
                return False

            return False

        except Exception as e:
            logger.debug("uninstrument_app error: %s", e, exc_info=True)
            return False



""" Usage scenarios:

# If auto_instrumentation = True - sinstrumentation happens automatically as :

# The user just passes their app instance (like Flask(app) or FastAPI()) into our SDK through config.framework_app.

# The SDK automatically detects the framework by checking the app’s attributes (Flask → wsgi_app, FastAPI → router, Django → WSGI/ASGI handlers).

# Based on the detected framework, the SDK applies the correct OpenTelemetry instrumentor (FlaskInstrumentor, ASGI middleware, DjangoInstrumentor).

# The user doesn’t need to configure anything manually 


# If auto_instrumentation = False, then the behavior is:

# The SDK will NOT auto-detect any framework (Flask/Django/FastAPI).

# No automatic tracing, metrics, or middleware will be added to the app.

# The user must explicitly call: tele.instrument_app(app, framework="flask")

# Only then does the SDK apply the correct instrumentor—otherwise, the framework is completely untouched."""