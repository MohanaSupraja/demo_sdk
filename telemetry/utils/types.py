from typing import Dict, Any, Union

class Observation:
    def __init__(self, value: Union[int,float], attributes: Dict[str,Any]=None):
        self.value = value
        self.attributes = attributes or {}
