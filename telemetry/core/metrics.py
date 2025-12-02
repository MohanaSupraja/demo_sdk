import logging
from typing import Dict, Any, Callable, Optional

logger = logging.getLogger(__name__)
if not logger.handlers:
    logging.basicConfig(level=logging.WARNING)

try:
    from opentelemetry import metrics as ot_metrics
except Exception:
    ot_metrics = None


# ---------------- NO-OP FALLBACK TYPES -------------------

class _NoopCounter:
    def add(self, value: float = 1.0, attributes: Dict[str, Any] = None):
        return None

class _NoopUpDownCounter:
    def add(self, value: float = 1.0, attributes: Dict[str, Any] = None):
        return None

class _NoopHistogram:
    def record(self, value: float, attributes: Dict[str, Any] = None):
        return None

class _NoopObservable:
    def __init__(self):
        self.callback = None


# ---------------------------------------------------------
#                METRIC MANAGER (FINAL VERSION)
# ---------------------------------------------------------

class MetricsManager:
    """
    Production-grade metrics manager supporting:
      ✔ Counter
      ✔ UpDownCounter
      ✔ Histogram
      ✔ Observable Gauge
      ✔ Observable Counter
      ✔ Observable UpDownCounter
    With auto-noop fallback & safe instrumentation recreation.
    """

    def __init__(self, meter_provider=None):
        self.meter_provider = meter_provider
        self._instruments: Dict[str, Any] = {}
        self._observable_callbacks: Dict[str, Any] = {}

    # ------------------- METER HELPERS ---------------------

    def get_meter(self, name: str):
        """Return a meter from provider or fallback to ot_metrics."""
        try:
            if self.meter_provider:
                return self.meter_provider.get_meter(name)
            if ot_metrics:
                return ot_metrics.get_meter(name)
        except Exception as e:
            logger.debug("get_meter failed for %s: %s", name, e, exc_info=True)
        return None

    def _is_noop(self, inst: Any) -> bool:
        return isinstance(inst, (_NoopCounter, _NoopUpDownCounter, _NoopHistogram, _NoopObservable))

    # ------------------- GENERIC CREATION HELPER ---------------------

    def _get_or_create(self, name: str, inst_type: str,
                       description: Optional[str],
                       unit: Optional[str]):

        existing = self._instruments.get(name)
        if existing and not self._is_noop(existing):
            return existing

        if existing and self._is_noop(existing):
            logger.debug(f"Attempting to replace noop instrument '{name}'.")

        meter = self.get_meter(name)

        try:
            if meter:
                kwargs = {}
                if description: kwargs["description"] = description
                if unit: kwargs["unit"] = unit

                # mapping to real otel API
                creator_map = {
                    "counter": meter.create_counter,
                    "updown": meter.create_up_down_counter,
                    "histogram": meter.create_histogram,
                }

                if inst_type in creator_map:
                    inst = creator_map[inst_type](name, **kwargs)
                    self._instruments[name] = inst
                    logger.info("Created real %s '%s'", inst_type, name)
                    return inst

        except Exception as e:
            logger.debug(f"Failed to create {inst_type} '{name}': {e}", exc_info=True)

        # fallback to noop
        noop_map = {
            "counter": _NoopCounter(),
            "updown": _NoopUpDownCounter(),
            "histogram": _NoopHistogram(),
        }
        noop = noop_map[inst_type]
        self._instruments[name] = noop

        logger.warning(
            f"Using NOOP {inst_type} for '{name}'. "
            f"Install OpenTelemetry or configure a meter provider."
        )
        return noop

    # ------------------- COUNTERS ---------------------

    def increment_counter(self, name: str, value: float = 1.0, attributes: Dict[str, Any] = None):
        inst = self._get_or_create(name, "counter", description="", unit="")
        try:
            inst.add(value, attributes or {})
        except Exception:
            logger.debug("Error incrementing counter '%s'", name, exc_info=True)

    def create_counter(self, name: str, description=None, unit=None):
        return self._get_or_create(name, "counter", description, unit)

    # ------------------- UP-DOWN COUNTERS ---------------------

    def add_updown(self, name: str, value: float = 1.0, attributes: Dict[str, Any] = None):
        inst = self._get_or_create(name, "updown", description="", unit="")
        try:
            inst.add(value, attributes or {})
        except Exception:
            logger.debug("Error updating updown counter '%s'", name, exc_info=True)

    def create_updown(self, name: str, description=None, unit=None):
        return self._get_or_create(name, "updown", description, unit)

    # ------------------- HISTOGRAM ----------------------

    def record_histogram(self, name: str, value: float, attributes: Dict[str, Any] = None, unit=None):
        inst = self._get_or_create(name, "histogram", description="", unit=unit)
        try:
            inst.record(value, attributes or {})
        except Exception:
            logger.debug("Error recording histogram '%s'", name, exc_info=True)

    def create_histogram(self, name: str, description=None, unit=None):
        return self._get_or_create(name, "histogram", description, unit)

    # ------------------- OBSERVABLE METRICS ---------------------

    def create_observable_gauge(self, name: str, callback: Callable):
        return self._create_observable(name, callback, inst_type="gauge")

    def create_observable_counter(self, name: str, callback: Callable):
        return self._create_observable(name, callback, inst_type="counter")

    def create_observable_updown(self, name: str, callback: Callable):
        return self._create_observable(name, callback, inst_type="updown")

    def _create_observable(self, name: str, callback: Callable, inst_type: str):
        meter = self.get_meter(name)

        try:
            if meter:
                if inst_type == "gauge":
                    observable = meter.create_observable_gauge(name, callbacks=[callback])
                elif inst_type == "counter":
                    observable = meter.create_observable_counter(name, callbacks=[callback])
                else:
                    observable = meter.create_observable_up_down_counter(name, callbacks=[callback])

                self._instruments[name] = observable
                self._observable_callbacks[name] = callback
                logger.info("Created observable %s '%s'", inst_type, name)
                return observable

        except Exception as e:
            logger.debug(f"Failed to create observable {inst_type} '{name}': {e}", exc_info=True)

        # fallback noop
        noop = _NoopObservable()
        noop.callback = callback
        self._instruments[name] = noop
        return noop

    # --------------------- FLUSH ------------------------

    def flush(self):
        try:
            if self.meter_provider and hasattr(self.meter_provider, "shutdown"):
                self.meter_provider.shutdown()
        except Exception:
            logger.debug("Error flushing meter provider", exc_info=True)





"""Creates and records all OpenTelemetry metric types with automatic fallback when OTel is not installed.

It supports SIX major metric instruments

Counter – for increasing values (increment_counter)

UpDownCounter – values that increase OR decrease (add_updown)

Histogram – distribution measurements (record_histogram)

Observable Gauge – callback-based metrics (create_observable_gauge)

Observable Counter – callback counter

Observable UpDownCounter – callback up/down counter

1. get_meter()

Finds or creates a meter from the configured meter_provider, fallback to OTel global.

2. _get_or_create()

Creates real counter/updown/histogram if possible

Replaces NOOP instruments when OTel becomes available

Ensures no crashes if OTel is missing

3. Counter operations

create_counter() → create or fetch

increment_counter() → add a value safely

4. UpDownCounter operations

create_updown()

add_updown()

5. Histogram operations

create_histogram()

record_histogram()

6. Observable metrics

Creates callback-based metrics:

create_observable_gauge(callback)

create_observable_counter(callback)

create_observable_updown(callback)

7. Flush

flush() calls meter_provider shutdown if supported to flush pending metrics."""