"""Resource accounting for Kubernetes-like YAFS placement policies."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Optional


class ResourceAccounting:
    """Track CPU, RAM, and bandwidth usage on topology nodes.

    The accounting state is stored on the YAFS topology node attributes so it
    remains visible to existing analysis code.  Bandwidth is optional: if a
    node has no explicit bandwidth capacity, a conservative capacity is
    inferred from incident links, falling back to ``default_node_bw``.
    """

    CPU_KEYS = ("CPU", "cpu", "CPU_capacity", "cpu_capacity")
    RAM_KEYS = ("RAM", "ram", "RAM_capacity", "ram_capacity")
    BW_KEYS = ("BW", "bandwidth", "BANDWIDTH", "BW_capacity", "bw_capacity")

    def __init__(self, topology, default_node_bw: float = 1000.0) -> None:
        self.topology = topology
        self.default_node_bw = float(default_node_bw)
        self.allocations: dict[tuple[str, str, int], int] = defaultdict(int)
        self._ensure_usage_fields()

    def can_fit(self, node_id: int, service_profile: dict[str, Any]) -> bool:
        """Return True when the node can host the service profile."""
        return len(self.reasons_not_fit(node_id, service_profile)) == 0

    def reasons_not_fit(
        self, node_id: int, service_profile: dict[str, Any]
    ) -> list[str]:
        """Return human-readable filter failures for a node/profile pair."""
        node = self._node(node_id)
        capacity = self.node_capacity(node_id)
        available = self.node_available(node_id)
        reasons: list[str] = []

        allowed_layers = service_profile.get("allowed_layers") or []
        node_layer = node.get("type")
        if allowed_layers and node_layer not in allowed_layers:
            reasons.append(
                f"forbidden layer: node={node_layer}, allowed={allowed_layers}"
            )

        if available["CPU"] < self._req(service_profile, "CPU_req"):
            reasons.append(
                "insufficient CPU: "
                f"available={available['CPU']:.3f}, "
                f"required={self._req(service_profile, 'CPU_req'):.3f}, "
                f"capacity={capacity['CPU']:.3f}"
            )

        if available["RAM"] < self._req(service_profile, "RAM_req"):
            reasons.append(
                "insufficient RAM: "
                f"available={available['RAM']:.3f}, "
                f"required={self._req(service_profile, 'RAM_req'):.3f}, "
                f"capacity={capacity['RAM']:.3f}"
            )

        if available["BW"] < self._req(service_profile, "BW_req"):
            reasons.append(
                "insufficient BW: "
                f"available={available['BW']:.3f}, "
                f"required={self._req(service_profile, 'BW_req'):.3f}, "
                f"capacity={capacity['BW']:.3f}"
            )

        return reasons

    def commit(
        self,
        node_id: int,
        app_name: str,
        module_name: str,
        service_profile: dict[str, Any],
    ) -> None:
        """Reserve resources for a module placement on ``node_id``."""
        node = self._node(node_id)
        node["CPU_used"] = self._used(node, "CPU_used") + self._req(
            service_profile, "CPU_req"
        )
        node["RAM_used"] = self._used(node, "RAM_used") + self._req(
            service_profile, "RAM_req"
        )
        node["BW_used"] = self._used(node, "BW_used") + self._req(
            service_profile, "BW_req"
        )
        self.allocations[(app_name, module_name, node_id)] += 1

    def release(
        self,
        node_id: int,
        app_name: str,
        module_name: str,
        service_profile: dict[str, Any],
    ) -> None:
        """Release resources for a module placement on ``node_id``."""
        node = self._node(node_id)
        node["CPU_used"] = self._used(node, "CPU_used") - self._req(
            service_profile, "CPU_req"
        )
        node["RAM_used"] = self._used(node, "RAM_used") - self._req(
            service_profile, "RAM_req"
        )
        node["BW_used"] = self._used(node, "BW_used") - self._req(
            service_profile, "BW_req"
        )
        key = (app_name, module_name, node_id)
        if self.allocations.get(key, 0) > 1:
            self.allocations[key] -= 1
        else:
            self.allocations.pop(key, None)

    def move(
        self,
        app_name: str,
        module_name: str,
        source_node: int,
        target_node: int,
        service_profile: dict[str, Any],
    ) -> None:
        """Move accounting from source to target.

        This only updates resource counters.  It intentionally does not move
        YAFS DES processes; runtime migration is a later phase.
        """
        self.release(source_node, app_name, module_name, service_profile)
        self.commit(target_node, app_name, module_name, service_profile)

    def dominant_share(
        self, node_id: int, service_profile: dict[str, Any]
    ) -> float:
        """Compute the DRF dominant share for a service on a node."""
        capacity = self.node_capacity(node_id)
        shares = [
            self._safe_ratio(self._req(service_profile, "CPU_req"), capacity["CPU"]),
            self._safe_ratio(self._req(service_profile, "RAM_req"), capacity["RAM"]),
        ]
        bw_req = self._req(service_profile, "BW_req")
        if capacity["BW"] > 0 and bw_req > 0:
            shares.append(self._safe_ratio(bw_req, capacity["BW"]))
        return max(shares) if shares else 0.0

    def node_available(self, node_id: int) -> dict[str, float]:
        """Return available CPU, RAM, and BW for ``node_id``."""
        capacity = self.node_capacity(node_id)
        usage = self.node_usage(node_id)
        return {
            "CPU": capacity["CPU"] - usage["CPU"],
            "RAM": capacity["RAM"] - usage["RAM"],
            "BW": capacity["BW"] - usage["BW"],
        }

    def node_usage(self, node_id: int) -> dict[str, float]:
        """Return used CPU, RAM, and BW for ``node_id``."""
        node = self._node(node_id)
        node.setdefault("CPU_used", 0.0)
        node.setdefault("RAM_used", 0.0)
        node.setdefault("BW_used", 0.0)
        return {
            "CPU": self._used(node, "CPU_used"),
            "RAM": self._used(node, "RAM_used"),
            "BW": self._used(node, "BW_used"),
        }

    def node_capacity(self, node_id: int) -> dict[str, float]:
        """Return CPU, RAM, and BW capacity for ``node_id``."""
        node = self._node(node_id)
        return {
            "CPU": self._first_numeric(node, self.CPU_KEYS, 0.0),
            "RAM": self._first_numeric(node, self.RAM_KEYS, 0.0),
            "BW": self._node_bw_capacity(node_id),
        }

    def validate_no_negative_usage(self) -> bool:
        """Return True when no node has negative resource usage."""
        return len(self.negative_usage_violations()) == 0

    def validate_capacity_constraints(self) -> bool:
        """Return True when no node exceeds CPU, RAM, or BW capacity."""
        return len(self.capacity_violations()) == 0

    def negative_usage_violations(self) -> list[dict[str, Any]]:
        violations = []
        for node_id in self.topology.G.nodes:
            usage = self.node_usage(node_id)
            for resource, value in usage.items():
                if value < -1e-9:
                    violations.append(
                        {
                            "node_id": node_id,
                            "resource": resource,
                            "used": value,
                        }
                    )
        return violations

    def capacity_violations(self) -> list[dict[str, Any]]:
        violations = []
        for node_id in self.topology.G.nodes:
            capacity = self.node_capacity(node_id)
            usage = self.node_usage(node_id)
            for resource, used in usage.items():
                if capacity[resource] > 0 and used > capacity[resource] + 1e-9:
                    violations.append(
                        {
                            "node_id": node_id,
                            "resource": resource,
                            "used": used,
                            "capacity": capacity[resource],
                        }
                    )
        return violations

    def summary(self) -> dict[str, Any]:
        """Return a compact, debug-friendly accounting summary."""
        nodes = {}
        totals = {
            "CPU_used": 0.0,
            "CPU_capacity": 0.0,
            "RAM_used": 0.0,
            "RAM_capacity": 0.0,
            "BW_used": 0.0,
            "BW_capacity": 0.0,
        }

        for node_id in sorted(self.topology.G.nodes):
            node = self._node(node_id)
            usage = self.node_usage(node_id)
            capacity = self.node_capacity(node_id)
            available = self.node_available(node_id)
            nodes[node_id] = {
                "name": node.get("name", str(node_id)),
                "type": node.get("type", "unknown"),
                "role": node.get("role", "unknown"),
                "usage": usage,
                "capacity": capacity,
                "available": available,
            }
            totals["CPU_used"] += usage["CPU"]
            totals["CPU_capacity"] += capacity["CPU"]
            totals["RAM_used"] += usage["RAM"]
            totals["RAM_capacity"] += capacity["RAM"]
            totals["BW_used"] += usage["BW"]
            totals["BW_capacity"] += capacity["BW"]

        return {
            "nodes": nodes,
            "totals": totals,
            "negative_usage_violations": self.negative_usage_violations(),
            "capacity_violations": self.capacity_violations(),
            "placements_tracked": sum(self.allocations.values()),
        }

    def _ensure_usage_fields(self) -> None:
        for node_id in self.topology.G.nodes:
            node = self._node(node_id)
            node.setdefault("CPU_used", 0.0)
            node.setdefault("RAM_used", 0.0)
            node.setdefault("BW_used", 0.0)

    def _node(self, node_id: int) -> dict[str, Any]:
        return self.topology.G.nodes[node_id]

    def _node_bw_capacity(self, node_id: int) -> float:
        node = self._node(node_id)
        explicit = self._first_numeric(node, self.BW_KEYS, None)
        if explicit is not None:
            return explicit

        incident = []
        graph = self.topology.G
        for _, _, attrs in graph.edges(node_id, data=True):
            bw = self._first_numeric(attrs, ("BW", "bandwidth", "BANDWIDTH"), None)
            if bw is not None:
                incident.append(bw)
        if hasattr(graph, "in_edges"):
            for _, _, attrs in graph.in_edges(node_id, data=True):
                bw = self._first_numeric(attrs, ("BW", "bandwidth", "BANDWIDTH"), None)
                if bw is not None:
                    incident.append(bw)

        if incident:
            return min(incident)
        return self.default_node_bw

    @staticmethod
    def _req(service_profile: dict[str, Any], key: str) -> float:
        try:
            value = service_profile.get(key, 0.0)
            if value is None:
                return 0.0
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _used(node: dict[str, Any], key: str) -> float:
        try:
            value = node.get(key, 0.0)
            if value is None:
                return 0.0
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _first_numeric(
        data: dict[str, Any], keys: tuple[str, ...], default: Optional[float]
    ) -> Optional[float]:
        for key in keys:
            if key in data:
                try:
                    value = data[key]
                    if value is None:
                        continue
                    return float(value)
                except (TypeError, ValueError):
                    continue
        return default

    @staticmethod
    def _safe_ratio(value: float, capacity: float) -> float:
        if capacity <= 0:
            return 0.0
        return value / capacity
