from typing import Dict, Any
try:
    from opentelemetry.propagate import inject as _inject, extract as _extract
    def inject(carrier: Dict[str,Any], context=None):
        _inject(carrier)
    def extract(carrier: Dict[str,Any]):
        return _extract(carrier)
except Exception:
    def inject(carrier: Dict[str,Any], context=None):
        return carrier
    def extract(carrier: Dict[str,Any]):
        return None
