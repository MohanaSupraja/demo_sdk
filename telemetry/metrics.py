

import logging
from typing import Dict, Any, Callable

logger = logging.getLogger(__name__)
# configure basic logging if not already configured by the app
if not logger.handlers:
    logging.basicConfig(level=logging.WARNING)

try:
    from opentelemetry import metrics as ot_metrics
except Exception:
    ot_metrics = None


class _NoopCounter:
    def add(self, value: float = 1.0, attributes: Dict[str, Any] = None):
        # noop fallback for environments without OTel
        return None


class _NoopHistogram:
    def record(self, value: float, attributes: Dict[str, Any] = None):
        # noop fallback
        return None


class MetricsManager:
    def __init__(self, meter_provider=None):
        self.meter_provider = meter_provider
        # _instruments keyed by name -> instrument object (counter/histogram) or noop wrapper
        self._instruments: Dict[str, Any] = {}

    def set_meter_provider(self, meter_provider) -> None:
        """
        Set/replace the meter_provider. Optionally call this when user configures telemetry
        at runtime. We do not auto-rebuild all instruments here — create/usage will trigger
        replacement per-instrument.
        """
        self.meter_provider = meter_provider
        logger.info("Meter provider set on MetricsManager.")

    def _is_noop(self, inst: Any) -> bool:
        return isinstance(inst, (_NoopCounter, _NoopHistogram))

    def get_meter(self, name: str):
        """Return a meter from provider or ot_metrics; return None on failure."""
        try:
            if self.meter_provider:
                # meter_provider expected to implement get_meter(name)
                return self.meter_provider.get_meter(name)
            if ot_metrics:
                # opentelemetry.metrics.get_meter(name)
                return ot_metrics.get_meter(name)
        except Exception as e:
            # Don't raise, but log at debug so user can optionally see details
            logger.debug("get_meter failed for %s: %s", name, e, exc_info=True)
            return None
        return None

    def create_counter(self, name: str, description: str = None, unit: str = None):
        """
        Create or return an existing counter instrument.
        If a cached noop is present, attempt to replace only that entry with a real instrument.
        """
        # If instrument exists and is not a noop, return it immediately
        inst = self._instruments.get(name)
        if inst and not self._is_noop(inst):
            return inst

        # If the cached instrument is a noop, attempt to replace it
        if inst and self._is_noop(inst):
            logger.warning(
                "Found cached noop for counter '%s'. Attempting to recreate a real counter.", name
            )

        meter = self.get_meter(name)
        try:
            if meter and hasattr(meter, "create_counter"):
                kwargs = {}
                if description is not None:
                    kwargs["description"] = description
                if unit is not None:
                    kwargs["unit"] = unit
                c = meter.create_counter(name, **kwargs)
                self._instruments[name] = c
                logger.info("Created real counter '%s' and replaced noop (if any).", name)
                return c
        except Exception as e:
            # fall through to noop fallback but log at debug
            logger.debug("Failed to create real counter '%s': %s", name, e, exc_info=True)

        # If we reach here: either meter not available or creation failed.
        # If there was already a noop cached, keep it; otherwise create & cache one.
        if inst and self._is_noop(inst):
            logger.warning(
                "Using existing noop counter for '%s' (real meter not available).", name
            )
            return inst

        noop = _NoopCounter()
        self._instruments[name] = noop
        logger.warning(
            "No meter available — created noop counter for '%s'. To enable real metrics, "
            "configure a meter provider or install OpenTelemetry.", name
        )
        return noop

    def increment_counter(self, name: str, value: float = 1.0, attributes: Dict[str, Any] = None):
        """
        Increment a counter. If the instrument does not exist, create one with defaults.
        If the cached instrument is a noop, attempt to recreate it before using.
        """
        attrs = attributes or {}
        inst = self._instruments.get(name)

        # If cached noop exists, try to replace it with a real instrument
        if inst and self._is_noop(inst):
            logger.debug("Cached noop detected for '%s' on increment; trying to recreate.", name)
            inst = self.create_counter(name, description="", unit="")

        if not inst:
            # create a counter with empty description/unit (safe default)
            inst = self.create_counter(name, description="", unit="")

        try:
            if hasattr(inst, "add"):
                inst.add(value, attrs)
            else:
                # support callable fallback (older code patterns)
                inst(value, attrs)
        except Exception:
            # swallow errors to keep SDK non-breaking in user apps, but log debug
            logger.debug("Error while incrementing counter '%s'.", name, exc_info=True)

    def create_histogram(self, name: str, description: str = None, unit: str = None):
        """
        Create or return an existing histogram instrument.
        If a cached noop is present, attempt to replace only that entry with a real instrument.
        """
        inst = self._instruments.get(name)
        if inst and not self._is_noop(inst):
            return inst

        if inst and self._is_noop(inst):
            logger.warning(
                "Found cached noop for histogram '%s'. Attempting to recreate a real histogram.", name
            )

        meter = self.get_meter(name)
        try:
            if meter and hasattr(meter, "create_histogram"):
                kwargs = {}
                if description is not None:
                    kwargs["description"] = description
                if unit is not None:
                    kwargs["unit"] = unit
                h = meter.create_histogram(name, **kwargs)
                self._instruments[name] = h
                logger.info("Created real histogram '%s' and replaced noop (if any).", name)
                return h
        except Exception as e:
            logger.debug("Failed to create real histogram '%s': %s", name, e, exc_info=True)

        if inst and self._is_noop(inst):
            logger.warning(
                "Using existing noop histogram for '%s' (real meter not available).", name
            )
            return inst

        noop = _NoopHistogram()
        self._instruments[name] = noop
        logger.warning(
            "No meter available — created noop histogram for '%s'. To enable real metrics, "
            "configure a meter provider or install OpenTelemetry.", name
        )
        return noop

    def record_histogram(self, name: str, value: float = 0.0, attributes: Dict[str, Any] = None, unit: str = None):
        """
        Record a value into a histogram. Creates the instrument if missing.
        If a cached noop exists, attempt to replace it before recording.
        """
        attrs = attributes or {}
        inst = self._instruments.get(name)

        # If cached noop exists, try to replace it with a real instrument
        if inst and self._is_noop(inst):
            logger.debug("Cached noop detected for '%s' on record; trying to recreate.", name)
            inst = self.create_histogram(name, description="", unit=unit)

        if not inst:
            inst = self.create_histogram(name, description="", unit=unit)

        try:
            if hasattr(inst, "record"):
                inst.record(value, attrs)
            else:
                # some implementations might expose `observe` or be callable; try to be permissive
                if callable(inst):
                    inst(value, attrs)
        except Exception:
            logger.debug("Error while recording histogram '%s'.", name, exc_info=True)

    def flush(self):
        """
        Optional: if your implementation needs explicit flushing, implement it here.
        No-op by default.
        """
        # Example: if meter_provider has a shutdown or flush, call it.
        try:
            if self.meter_provider and hasattr(self.meter_provider, "shutdown"):
                self.meter_provider.shutdown()
        except Exception:
            logger.debug("Error while flushing meter provider.", exc_info=True)
