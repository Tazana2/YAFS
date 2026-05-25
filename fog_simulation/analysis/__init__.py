"""Analysis helpers for YAFS post-run outputs."""

__all__ = ["analyze_results", "export_resource_usage_outputs", "export_slo_outputs"]


def __getattr__(name):
    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    from . import results

    return getattr(results, name)
