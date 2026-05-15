"""Service metadata helpers for scheduler resource accounting.

The YAFS ``Application`` object already keeps module attributes in
``app.data``.  This module gives those free-form dictionaries a stable schema
without changing the application factories or the YAFS core.
"""

from __future__ import annotations

from typing import Any, Optional


DEFAULT_SERVICE_PROFILE: dict[str, Any] = {
    "CPU_req": 0.0,
    "RAM_req": 0.0,
    "BW_req": 0.0,
    "CPU_limit": None,
    "RAM_limit": None,
    "service_class": None,
    "slo_ms_p99": None,
    "allowed_layers": [],
    "preferred_role": None,
    "priority": 0,
    "cooldown_windows": 0,
}


def get_module_attrs(app, module_name: str) -> dict[str, Any]:
    """Return raw metadata for ``module_name`` from ``app.data``."""
    for entry in getattr(app, "data", []) or []:
        name = list(entry.keys())[0]
        if name == module_name:
            return dict(list(entry.values())[0])
    return {}


def normalize_service_profile(
    app_name: str,
    module_name: str,
    attrs: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Return a defaulted service profile used by schedulers.

    Existing application fields are preserved.  Missing ``RAM_req`` falls back
    to the legacy ``RAM`` field, and missing bandwidth defaults to zero so the
    current simulations keep their placement behavior.
    """
    raw = dict(attrs or {})
    profile = dict(DEFAULT_SERVICE_PROFILE)
    profile.update(raw)

    profile["app"] = app_name
    profile["module"] = module_name
    profile["CPU_req"] = _as_float(profile.get("CPU_req"), 0.0)
    profile["RAM_req"] = _as_float(profile.get("RAM_req", raw.get("RAM")), 0.0)
    if profile["RAM_req"] == 0.0:
        profile["RAM_req"] = _as_float(raw.get("RAM"), 0.0)
    profile["BW_req"] = _as_float(profile.get("BW_req"), 0.0)
    profile["priority"] = int(_as_float(profile.get("priority"), 0.0))
    profile["cooldown_windows"] = int(
        _as_float(profile.get("cooldown_windows"), 0.0)
    )

    allowed_layers = profile.get("allowed_layers") or []
    if isinstance(allowed_layers, str):
        allowed_layers = [allowed_layers]
    profile["allowed_layers"] = list(allowed_layers)

    return profile


def _as_float(value: Any, default: float) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default
