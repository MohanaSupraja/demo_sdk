from typing import Dict,Any, List

def mask_sensitive(attrs: Dict[str,Any], sensitive_fields: List[str]=None) -> Dict[str,Any]:
    if not attrs or not sensitive_fields:
        return attrs or {}
    out = {}
    for k,v in attrs.items():
        if any(field in k.lower() for field in sensitive_fields):
            out[k] = "****"
        else:
            out[k] = v
    return out
