"""Latency/resource-aware initial placement scheduler for YAFS.

This scheduler is intentionally limited to initial allocation.  It does not
perform runtime migration, rescheduling, eviction, or RL-based decisions.
"""

from __future__ import annotations

import csv
import math
from pathlib import Path
from typing import Any, Optional

import networkx as nx
from yafs.application import Application
from yafs.placement import Placement

from fog_simulation.simulation.resource_accounting import ResourceAccounting
from fog_simulation.simulation.service_metadata import (
    get_module_attrs,
    normalize_service_profile,
)


class LatencyResourceAwareScheduler(Placement):
    """Kubernetes-like initial scheduler with network and resource scoring."""

    def __init__(
        self,
        name: str,
        verbose: bool = True,
        resource_accounting: Optional[ResourceAccounting] = None,
        default_node_bw: float = 1000.0,
        w_latency: float = 0.35,
        w_resource_balance: float = 0.25,
        w_drf: float = 0.20,
        w_bandwidth: float = 0.15,
        w_role: float = 0.05,
    ) -> None:
        super().__init__(name)
        self.verbose = verbose
        self.resource_accounting = resource_accounting
        self.default_node_bw = default_node_bw
        self.weights = {
            "latency": float(w_latency),
            "resource_balance": float(w_resource_balance),
            "drf": float(w_drf),
            "bandwidth": float(w_bandwidth),
            "role": float(w_role),
        }
        self._decisions: list[dict[str, Any]] = []
        self._failed_decisions: list[dict[str, Any]] = []
        self._placements_by_app: dict[str, dict[str, list[int]]] = {}

    def initial_allocation(self, sim, app_name: str) -> None:
        app = sim.apps[app_name]
        topology = sim.topology
        accounting = self._get_resource_accounting(topology)
        module_attrs = self._module_attrs(app)

        if self.verbose:
            print(f"\n[LatencyResource Scheduler] Scheduling app '{app_name}'")
            print(f"  Modules to schedule: {list(app.services.keys())}")

        scheduled = 0
        skipped = 0
        failed = 0

        for module_name, services in app.services.items():
            attrs = module_attrs.get(module_name, get_module_attrs(app, module_name))
            node_type = attrs.get("Type", Application.TYPE_MODULE)

            if node_type == Application.TYPE_SOURCE:
                if self.verbose:
                    print(f"  [skip-src ] {module_name} - pure source, pinned by deploy_source()")
                skipped += 1
                continue
            if node_type == Application.TYPE_SINK:
                if self.verbose:
                    print(f"  [skip-sink] {module_name} - pure sink, pinned by deploy_sink()")
                skipped += 1
                continue

            pod = normalize_service_profile(app_name, module_name, attrs)
            candidates, rejected = self._filter_nodes(topology, pod, accounting)

            if not candidates:
                print(
                    f"  [LatencyResource Scheduler] WARNING - no feasible node "
                    f"for '{module_name}' in '{app_name}'. Module not deployed."
                )
                if self.verbose and rejected:
                    print("    rejection summary:")
                    for node_id, reasons in list(rejected.items())[:5]:
                        node = topology.G.nodes[node_id]
                        print(f"      - {node.get('name', node_id)}: {', '.join(reasons)}")
                    if len(rejected) > 5:
                        print(f"      - ... {len(rejected) - 5} more rejected nodes")
                self._failed_decisions.append(
                    {"app": app_name, "module": module_name, "rejected_nodes": rejected}
                )
                failed += 1
                skipped += 1
                continue

            best_node, score_details = self._score_nodes(
                sim=sim,
                app=app,
                module_name=module_name,
                candidates=candidates,
                topology=topology,
                pod=pod,
                accounting=accounting,
            )

            sim.deploy_module(app_name, module_name, services, [best_node])
            accounting.commit(best_node, app_name, module_name, pod)
            self._placements_by_app.setdefault(app_name, {}).setdefault(
                module_name, []
            ).append(best_node)

            node_attrs = topology.G.nodes[best_node]
            scores = score_details[best_node]
            decision = {
                "app": app_name,
                "module": module_name,
                "node_id": best_node,
                "node_name": node_attrs.get("name", str(best_node)),
                "node_type": node_attrs.get("type"),
                "node_role": node_attrs.get("role"),
                "CPU_req": pod["CPU_req"],
                "RAM_req": pod["RAM_req"],
                "BW_req": pod["BW_req"],
                "allowed_layers": pod.get("allowed_layers", []),
                "service_class": pod.get("service_class"),
                "slo_ms_p99": pod.get("slo_ms_p99"),
                "latency_score": scores["latency_score"],
                "resource_balance_score": scores["resource_balance_score"],
                "drf_score": scores["drf_score"],
                "bandwidth_score": scores["bandwidth_score"],
                "preferred_role_score": scores["preferred_role_score"],
                "estimated_network_cost": scores["estimated_network_cost"],
                "final_score": scores["final_score"],
            }
            self._decisions.append(decision)
            scheduled += 1

            if self.verbose:
                print(
                    f"  [bind] {module_name:45s} -> {decision['node_name']:20s} "
                    f"final={decision['final_score']:6.2f}  "
                    f"lat={decision['latency_score']:5.1f}  "
                    f"bal={decision['resource_balance_score']:5.1f}  "
                    f"drf={decision['drf_score']:5.1f}  "
                    f"bw={decision['bandwidth_score']:5.1f}  "
                    f"role={decision['preferred_role_score']:5.1f}"
                )

        if self.verbose:
            print(
                f"  -> {scheduled} module(s) bound, {failed} failed, "
                f"{skipped - failed} source/sink(s) skipped."
            )
            self._print_accounting_debug_summary(accounting)
            print()

    def _filter_nodes(
        self,
        topology,
        pod: dict[str, Any],
        accounting: ResourceAccounting,
    ) -> tuple[list[int], dict[int, list[str]]]:
        candidates: list[int] = []
        rejected: dict[int, list[str]] = {}

        for node_id in topology.G.nodes:
            node = topology.G.nodes[node_id]

            if node.get("type") == "gateway":
                rejected[node_id] = ["gateway nodes are transit-only"]
                continue
            if node.get("unschedulable", False):
                rejected[node_id] = ["node is unschedulable"]
                continue

            reasons = accounting.reasons_not_fit(node_id, pod)
            if reasons:
                rejected[node_id] = reasons
            else:
                candidates.append(node_id)

        return candidates, rejected

    def _score_nodes(
        self,
        sim,
        app: Application,
        module_name: str,
        candidates: list[int],
        topology,
        pod: dict[str, Any],
        accounting: ResourceAccounting,
    ) -> tuple[int, dict[int, dict[str, float]]]:
        latency_costs = {
            node_id: self.estimate_network_cost(sim, app, module_name, node_id)
            for node_id in candidates
        }
        latency_scores = _inverse_normalize(latency_costs)
        details: dict[int, dict[str, float]] = {}
        weight_sum = sum(self.weights.values()) or 1.0

        for node_id in candidates:
            resource_balance_score = self._resource_balance_score(
                node_id, pod, accounting
            )
            drf_score = self._drf_score(node_id, pod, accounting)
            bandwidth_score = self._bandwidth_score(node_id, pod, accounting)
            preferred_role_score = self._preferred_role_score(
                topology.G.nodes[node_id], pod
            )
            latency_score = latency_scores[node_id]

            final_score = (
                self.weights["latency"] * latency_score
                + self.weights["resource_balance"] * resource_balance_score
                + self.weights["drf"] * drf_score
                + self.weights["bandwidth"] * bandwidth_score
                + self.weights["role"] * preferred_role_score
            ) / weight_sum

            details[node_id] = {
                "latency_score": round(latency_score, 4),
                "resource_balance_score": round(resource_balance_score, 4),
                "drf_score": round(drf_score, 4),
                "bandwidth_score": round(bandwidth_score, 4),
                "preferred_role_score": round(preferred_role_score, 4),
                "estimated_network_cost": round(latency_costs[node_id], 4),
                "final_score": round(final_score, 4),
            }

        best_node = min(
            candidates,
            key=lambda node_id: (-details[node_id]["final_score"], node_id),
        )
        return best_node, details

    def estimate_network_cost(
        self,
        sim,
        app: Application,
        module_name: str,
        candidate_node: int,
    ) -> float:
        """Estimate communication cost for placing ``module_name`` on a node."""
        communicating_modules = self._communicating_modules(app, module_name)
        endpoint_nodes: list[int] = []

        for other_module in communicating_modules:
            endpoint_nodes.extend(self._placed_nodes_for_module(sim, app.name, other_module))

        if not endpoint_nodes:
            for other_module, nodes in self._placements_by_app.get(app.name, {}).items():
                if other_module != module_name:
                    endpoint_nodes.extend(nodes)

        if endpoint_nodes:
            costs = [
                self._shortest_path_cost(sim.topology.G, candidate_node, endpoint)
                for endpoint in endpoint_nodes
            ]
            finite_costs = [cost for cost in costs if math.isfinite(cost)]
            if finite_costs:
                return sum(finite_costs) / len(finite_costs)
            return 1_000_000.0

        node = sim.topology.G.nodes[candidate_node]
        preferred_role = pod_preferred_role = get_module_attrs(app, module_name).get(
            "preferred_role"
        )
        if pod_preferred_role and node.get("role") == preferred_role:
            return 0.0
        if node.get("type") in (get_module_attrs(app, module_name).get("allowed_layers") or []):
            return 10.0
        return 50.0

    def _communicating_modules(self, app: Application, module_name: str) -> set[str]:
        modules: set[str] = set()
        for message in self._application_messages(app):
            if getattr(message, "src", None) == module_name:
                modules.add(message.dst)
            if getattr(message, "dst", None) == module_name:
                modules.add(message.src)
        return modules

    def _application_messages(self, app: Application) -> list[Any]:
        messages: dict[str, Any] = {}
        for message in getattr(app, "messages", {}).values():
            messages[getattr(message, "name", str(id(message)))] = message
        for services in getattr(app, "services", {}).values():
            for service in services:
                for key in ("message_in", "message_out"):
                    message = service.get(key)
                    if message:
                        messages[getattr(message, "name", str(id(message)))] = message
        return list(messages.values())

    def _placed_nodes_for_module(
        self,
        sim,
        app_name: str,
        module_name: str,
    ) -> list[int]:
        nodes: list[int] = []

        for node_id in self._placements_by_app.get(app_name, {}).get(module_name, []):
            nodes.append(node_id)

        for des_id in sim.alloc_module.get(app_name, {}).get(module_name, []):
            node_id = sim.alloc_DES.get(des_id)
            if node_id is not None:
                nodes.append(node_id)

        for source in sim.alloc_source.values():
            if source.get("app") == app_name and source.get("module") == module_name:
                nodes.append(source["id"])

        return sorted(set(nodes))

    def _shortest_path_cost(self, graph, source: int, target: int) -> float:
        if source == target:
            return 0.0
        try:
            return float(
                nx.shortest_path_length(
                    graph,
                    source=source,
                    target=target,
                    weight=self._edge_network_weight,
                )
            )
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return float("inf")

    @staticmethod
    def _edge_network_weight(_src, _dst, attrs: dict[str, Any]) -> float:
        for key in ("latency", "PR"):
            try:
                if key in attrs and attrs[key] is not None:
                    return max(float(attrs[key]), 0.0)
            except (TypeError, ValueError):
                continue
        return 1.0

    def _resource_balance_score(
        self,
        node_id: int,
        pod: dict[str, Any],
        accounting: ResourceAccounting,
    ) -> float:
        utilizations = self._projected_utilizations(node_id, pod, accounting)
        imbalance = max(utilizations.values()) - min(utilizations.values())
        return _clamp_score((1.0 - imbalance) * 100.0)

    def _drf_score(
        self,
        node_id: int,
        pod: dict[str, Any],
        accounting: ResourceAccounting,
    ) -> float:
        dominant_share = max(self._projected_utilizations(node_id, pod, accounting).values())
        return _clamp_score((1.0 - dominant_share) * 100.0)

    def _bandwidth_score(
        self,
        node_id: int,
        pod: dict[str, Any],
        accounting: ResourceAccounting,
    ) -> float:
        bw_req = _as_float(pod.get("BW_req"), 0.0)
        if bw_req <= 0:
            return 100.0
        available = accounting.node_available(node_id)["BW"]
        if available <= 0:
            return 0.0
        pressure = bw_req / available
        return _clamp_score((1.0 - pressure) * 100.0)

    @staticmethod
    def _preferred_role_score(node: dict[str, Any], pod: dict[str, Any]) -> float:
        preferred_role = pod.get("preferred_role")
        if not preferred_role:
            return 50.0
        return 100.0 if node.get("role") == preferred_role else 0.0

    def _projected_utilizations(
        self,
        node_id: int,
        pod: dict[str, Any],
        accounting: ResourceAccounting,
    ) -> dict[str, float]:
        capacity = accounting.node_capacity(node_id)
        usage = accounting.node_usage(node_id)
        return {
            "CPU": _safe_projected_ratio(
                usage["CPU"] + _as_float(pod.get("CPU_req"), 0.0),
                capacity["CPU"],
            ),
            "RAM": _safe_projected_ratio(
                usage["RAM"] + _as_float(pod.get("RAM_req"), 0.0),
                capacity["RAM"],
            ),
            "BW": _safe_projected_ratio(
                usage["BW"] + _as_float(pod.get("BW_req"), 0.0),
                capacity["BW"],
            ),
        }

    def write_placement_report(self, output_path) -> Optional[Path]:
        if not self._decisions:
            return None

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fieldnames = [
            "app",
            "module",
            "node_id",
            "node_name",
            "node_type",
            "node_role",
            "CPU_req",
            "RAM_req",
            "BW_req",
            "allowed_layers",
            "service_class",
            "slo_ms_p99",
            "latency_score",
            "resource_balance_score",
            "drf_score",
            "bandwidth_score",
            "preferred_role_score",
            "estimated_network_cost",
            "final_score",
        ]
        with output_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            for decision in self._decisions:
                row = dict(decision)
                row["allowed_layers"] = ",".join(row.get("allowed_layers") or [])
                writer.writerow({key: row.get(key, "") for key in fieldnames})
        return output_path

    def get_scheduling_report(self) -> str:
        if not self._decisions:
            return "No scheduling decisions recorded."

        lines = [
            f"{'App':<28} {'Module':<36} {'Node':<18} {'Final':>7} "
            f"{'Lat':>6} {'Bal':>6} {'DRF':>6} {'BW':>6} {'Role':>6} "
            f"{'Class':<24} {'p99':>6}",
            "-" * 160,
        ]
        for decision in self._decisions:
            slo_ms_p99 = decision.get("slo_ms_p99")
            slo_display = "n/a" if slo_ms_p99 is None else str(slo_ms_p99)
            service_class = decision.get("service_class") or "unknown"
            lines.append(
                f"{decision['app']:<28} {decision['module']:<36} "
                f"{decision['node_name']:<18} {decision['final_score']:>7.2f} "
                f"{decision['latency_score']:>6.1f} "
                f"{decision['resource_balance_score']:>6.1f} "
                f"{decision['drf_score']:>6.1f} "
                f"{decision['bandwidth_score']:>6.1f} "
                f"{decision['preferred_role_score']:>6.1f} "
                f"{service_class:<24} {slo_display:>6}"
            )
        return "\n".join(lines)

    def _get_resource_accounting(self, topology) -> ResourceAccounting:
        if self.resource_accounting is None:
            self.resource_accounting = ResourceAccounting(
                topology,
                default_node_bw=self.default_node_bw,
            )
        return self.resource_accounting

    def _print_accounting_debug_summary(
        self,
        accounting: ResourceAccounting,
        max_nodes: int = 8,
    ) -> None:
        summary = accounting.summary()
        totals = summary["totals"]
        print("  Resource accounting summary:")
        print(
            "    totals: "
            f"CPU {totals['CPU_used']:.2f}/{totals['CPU_capacity']:.2f}, "
            f"RAM {totals['RAM_used']:.2f}/{totals['RAM_capacity']:.2f} MB, "
            f"BW {totals['BW_used']:.2f}/{totals['BW_capacity']:.2f}"
        )
        print(
            "    validation: "
            f"negative_usage_violations={len(summary['negative_usage_violations'])}, "
            f"capacity_violations={len(summary['capacity_violations'])}"
        )

        used_nodes = [
            (node_id, node)
            for node_id, node in summary["nodes"].items()
            if any(value > 0 for value in node["usage"].values())
        ]
        if not used_nodes:
            print("    used nodes: none")
            return

        print("    used nodes:")
        for node_id, node in used_nodes[:max_nodes]:
            usage = node["usage"]
            capacity = node["capacity"]
            print(
                f"      - {node['name']} ({node_id}, {node['type']}/{node['role']}): "
                f"CPU {usage['CPU']:.2f}/{capacity['CPU']:.2f}, "
                f"RAM {usage['RAM']:.2f}/{capacity['RAM']:.2f}, "
                f"BW {usage['BW']:.2f}/{capacity['BW']:.2f}"
            )
        if len(used_nodes) > max_nodes:
            print(f"      - ... {len(used_nodes) - max_nodes} more used nodes")

    @staticmethod
    def _module_attrs(app: Application) -> dict[str, dict[str, Any]]:
        attrs_by_module: dict[str, dict[str, Any]] = {}
        for entry in getattr(app, "data", []) or []:
            module_name = list(entry.keys())[0]
            attrs_by_module[module_name] = dict(list(entry.values())[0])
        return attrs_by_module


def _inverse_normalize(values: dict[int, float]) -> dict[int, float]:
    finite_values = [value for value in values.values() if math.isfinite(value)]
    if not finite_values:
        return {key: 0.0 for key in values}

    min_value = min(finite_values)
    max_value = max(finite_values)
    if abs(max_value - min_value) < 1e-12:
        return {key: 100.0 if math.isfinite(value) else 0.0 for key, value in values.items()}

    scores = {}
    for key, value in values.items():
        if not math.isfinite(value):
            scores[key] = 0.0
        else:
            scores[key] = _clamp_score((max_value - value) / (max_value - min_value) * 100.0)
    return scores


def _safe_projected_ratio(used: float, capacity: float) -> float:
    if capacity <= 0:
        return 0.0
    return min(max(used / capacity, 0.0), 1.0)


def _clamp_score(value: float) -> float:
    return min(max(float(value), 0.0), 100.0)


def _as_float(value: Any, default: float) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default
