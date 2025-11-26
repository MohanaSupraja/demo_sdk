# import inspect, functools, logging
# logger = logging.getLogger(__name__)

# def instrument_class(cls, prefix=None):
#     for name, member in inspect.getmembers(cls, predicate=inspect.isfunction):
#         if name.startswith("_"): continue
#         orig = getattr(cls, name)
#         def make_wrapper(o, n):
#             def w(*args, **kwargs):
#                 try:
#                     from opentelemetry import trace
#                     tracer = trace.get_tracer(__name__)
#                     with tracer.start_as_current_span(f"{cls.__name__}.{n}"):
#                         return o(*args, **kwargs)
#                 except Exception:
#                     return o(*args, **kwargs)
#             return functools.wraps(o)(w)
#         setattr(cls, name, make_wrapper(orig, name))
#     logger.info("Instrumented class %s", cls)
#     return cls

# class ClassInstrumentor:
#     def instrument(self, cls, prefix=None):
#         return instrument_class(cls, prefix)
import inspect
import functools
import logging
 
logger = logging.getLogger(__name__)
 
 
def instrument_class(cls, telemetry, prefix=None):
    """
    Wrap all public methods of a class with tracing using the same model as decorators.
    """
 
    for name, method in inspect.getmembers(cls, predicate=inspect.isfunction):
        if name.startswith("_"):
            continue  # skip private methods
 
        original = getattr(cls, name)
 
        def make_wrapper(orig_fn, method_name):
            @functools.wraps(orig_fn)
            def wrapper(*args, **kwargs):
                tracer = telemetry.traces.tracer
                span_name = f"{cls.__name__}.{method_name}"
                try:
                    with tracer.start_as_current_span(span_name):
                        return orig_fn(*args, **kwargs)
                except Exception:
                    return orig_fn(*args, **kwargs)
 
            # attach telemetry for consistency
            wrapper._telemetry = telemetry
            return wrapper
 
        setattr(cls, name, make_wrapper(original, name))
 
    logger.info(f"Instrumented class {cls.__name__}")
    return cls
 
 
class ClassInstrumentor:
    def instrument(self, cls, telemetry, prefix=None):
        return instrument_class(cls, telemetry, prefix)