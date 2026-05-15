"""
K8s-style placement policy for YAFS fog simulations.

Implements the three-phase Kubernetes default scheduler algorithm:

  Phase 1 — Filtering
    NodeUnschedulable  : skips nodes with ``unschedulable=True`` (cordoned).
    NodeResourcesFit   : requires free CPU *and* RAM ≥ the module's requests.

  Phase 2 — Scoring  (both plugins weight = 1, so final = simple average)
    LeastAllocated           : favours nodes with most free resources post-bind.
    BalancedResourceAllocation: penalises imbalance between CPU and RAM usage.

  Phase 3 — Binding
    Deploys the module on the winning node and updates ``CPU_used``/``RAM_used``
    so subsequent scheduling decisions see accurate residual capacity.

Only ``TYPE_MODULE`` services go through the scheduler.  Pure sources
(``TYPE_SOURCE``) and sinks (``TYPE_SINK``) must be placed explicitly via
``sim.deploy_source`` / ``sim.deploy_sink`` — exactly as Kubernetes treats
DaemonSets and managed cloud endpoints.
"""

from typing import Optional

from yafs.placement import Placement
from yafs.application import Application

from fog_simulation.simulation.resource_accounting import ResourceAccounting
from fog_simulation.simulation.service_metadata import (
    get_module_attrs,
    normalize_service_profile,
)


class KubernetesDefaultScheduler(Placement):
    """
    YAFS Placement that replicates the default kube-scheduler behaviour.

    Parameters
    ----------
    name : str
        Unique placement policy name (required by the Placement base class).
    verbose : bool, optional
        If True, print a scheduling decision line for every module bound.
        Default: True.
    """

    def __init__(
        self,
        name,
        verbose: bool = True,
        resource_accounting: Optional[ResourceAccounting] = None,
        default_node_bw: float = 1000.0,
    ):
        super().__init__(name)
        self.verbose = verbose
        self.resource_accounting = resource_accounting
        self.default_node_bw = default_node_bw
        self._decisions: list[dict] = []   # log of all binding decisions
        self._failed_decisions: list[dict] = []
        """Records every scheduling decision made during initial_allocation."""

    # ------------------------------------------------------------------ #
    #  Public entry point                                                  #
    # ------------------------------------------------------------------ #

    def initial_allocation(self, sim, app_name: str) -> None:
        """
        Schedule all TYPE_MODULE services of *app_name* onto topology nodes.

        Called once per application by ``sim.deploy_app`` / the YAFS core.

        Parameters
        ----------
        sim : yafs.core.Sim
        app_name : str
        """
        app = sim.apps[app_name]
        topology = sim.topology
        accounting = self._get_resource_accounting(topology)

        # Build module_name → raw attribute dict from app.data
        # (app.data is the list passed to Application.set_modules())
        module_attrs: dict[str, dict] = {}
        for entry in app.data:
            m_name = list(entry.keys())[0]
            m_attrs = list(entry.values())[0]
            module_attrs[m_name] = m_attrs

        if self.verbose:
            print(f"\n[K8s Scheduler] Scheduling app '{app_name}'")
            print(f"  Modules to schedule: {list(app.services.keys())}")

        scheduled = 0
        skipped   = 0
        failed    = 0

        for module_name, services in app.services.items():
            attrs     = module_attrs.get(module_name, get_module_attrs(app, module_name))
            node_type = attrs.get("Type", Application.TYPE_MODULE)

            # Sources and sinks are never pod-scheduled
            if node_type == Application.TYPE_SOURCE:
                if self.verbose:
                    print(f"  [skip-src ] {module_name} — pure source, pinned by deploy_source()")
                skipped += 1
                continue
            if node_type == Application.TYPE_SINK:
                if self.verbose:
                    print(f"  [skip-sink] {module_name} — pure sink, pinned by deploy_sink()")
                skipped += 1
                continue

            # Build a scheduler profile while preserving existing app fields.
            pod = normalize_service_profile(app_name, module_name, attrs)

            # ── Phase 1: Filtering ────────────────────────────────────────
            candidates, rejected = self._filter_nodes(topology, pod, accounting)

            if not candidates:
                print(
                    f"  [K8s Scheduler] WARNING — no feasible node for "
                    f"'{module_name}' in '{app_name}'. Module not deployed."
                )
                if self.verbose and rejected:
                    print("    rejection summary:")
                    for node_id, reasons in list(rejected.items())[:5]:
                        node = topology.G.nodes[node_id]
                        node_name = node.get("name", str(node_id))
                        print(f"      - {node_name}: {', '.join(reasons)}")
                    if len(rejected) > 5:
                        print(f"      - ... {len(rejected) - 5} more rejected nodes")
                self._failed_decisions.append(
                    {
                        "app": app_name,
                        "module": module_name,
                        "rejected_nodes": rejected,
                    }
                )
                failed += 1
                skipped += 1
                continue

            # ── Phase 2: Scoring ──────────────────────────────────────────
            best_node, scores = self._score_nodes(
                candidates,
                topology,
                pod,
                accounting,
            )

            # ── Phase 3: Binding ──────────────────────────────────────────
            sim.deploy_module(app_name, module_name, services, [best_node])

            # Resource accounting is centralized so later DriftGuard phases can
            # reuse the same fit, commit, release, and validation logic.
            node_attrs = topology.G.nodes[best_node]
            accounting.commit(best_node, app_name, module_name, pod)

            # Record decision
            decision = {
                "app":       app_name,
                "module":    module_name,
                "node_id":   best_node,
                "node_name": node_attrs.get("name", str(best_node)),
                "score":     round(scores[best_node], 2),
                "CPU_req":   pod["CPU_req"],
                "RAM_req":   pod["RAM_req"],
                "BW_req":    pod["BW_req"],
                "service_class": pod.get("service_class"),
                "slo_ms_p99": pod.get("slo_ms_p99"),
                "allowed_layers": pod.get("allowed_layers", []),
                "allowed_layers_considered": bool(pod.get("allowed_layers")),
                "dominant_share": round(
                    accounting.dominant_share(best_node, pod), 4
                ),
            }
            self._decisions.append(decision)
            scheduled += 1

            if self.verbose:
                print(
                    f"  [bind] {module_name:45s} → {decision['node_name']:20s} "
                    f"score={decision['score']:6.2f}  "
                    f"CPU+{pod['CPU_req']}  RAM+{pod['RAM_req']}MB  "
                    f"BW+{pod['BW_req']}  class={pod.get('service_class')}  "
                    f"p99={pod.get('slo_ms_p99')}ms  "
                    f"dom={decision['dominant_share']:.4f}  "
                    f"layers={pod.get('allowed_layers') or 'any'} "
                    f"(checked={decision['allowed_layers_considered']})"
                )

        if self.verbose:
            print(
                f"  → {scheduled} module(s) bound, {failed} failed, "
                f"{skipped - failed} source/sink(s) skipped."
            )
            self._print_accounting_debug_summary(accounting)
            print()

    # ------------------------------------------------------------------ #
    #  Phase 1 — Filtering                                                 #
    # ------------------------------------------------------------------ #

    def _filter_nodes(
        self,
        topology,
        pod: dict,
        accounting: ResourceAccounting,
    ) -> tuple[list, dict]:
        """
        Return candidate node IDs that pass all filter plugins.

        Plugins implemented
        -------------------
        NodeUnschedulable  — skips nodes where ``unschedulable=True``.
        NodeResourcesFit   — requires ``free_cpu >= CPU_req`` AND
                             ``free_ram >= RAM_req``.
        """
        candidates = []
        rejected = {}

        for node_id in topology.G.nodes:
            node = topology.G.nodes[node_id]
            reasons = []

            # Gateways are transit-only network nodes and must never host modules.
            if node.get("type") == "gateway":
                rejected[node_id] = ["gateway nodes are transit-only"]
                continue

            # Plugin: NodeUnschedulable
            if node.get("unschedulable", False):
                rejected[node_id] = ["node is unschedulable"]
                continue

            # Plugin: NodeResourcesFit
            reasons.extend(accounting.reasons_not_fit(node_id, pod))
            if not reasons:
                candidates.append(node_id)
            else:
                rejected[node_id] = reasons

        return candidates, rejected

    # ------------------------------------------------------------------ #
    #  Phase 2 — Scoring                                                   #
    # ------------------------------------------------------------------ #

    def _score_nodes(
        self,
        candidates: list,
        topology,
        pod: dict,
        accounting: ResourceAccounting,
    ) -> tuple[int, dict]:
        """
        Score each candidate and return ``(best_node_id, scores_dict)``.

        Score plugins (weight = 1 each, final = simple average)
        ---------------------------------------------------------
        LeastAllocated
            Favours nodes with more free resources **after** placing the pod.
            score = ((1 - cpu_frac_post) + (1 - ram_frac_post)) / 2 × 100

        BalancedResourceAllocation
            Penalises imbalance between CPU and RAM utilisation post-bind.
            score = (1 - |cpu_frac_post − ram_frac_post|) × 100
        """
        cpu_req = pod["CPU_req"]
        ram_req = pod["RAM_req"]
        scores: dict[int, float] = {}

        for node_id in candidates:
            capacity = accounting.node_capacity(node_id)
            usage = accounting.node_usage(node_id)

            cpu_cap = max(capacity["CPU"], 1)   # guard against 0-capacity nodes
            ram_cap = max(capacity["RAM"], 1)

            cpu_frac = (usage["CPU"] + cpu_req) / cpu_cap
            ram_frac = (usage["RAM"] + ram_req) / ram_cap

            # Clamp fractions to [0, 1] for numerical safety
            cpu_frac = min(max(cpu_frac, 0.0), 1.0)
            ram_frac = min(max(ram_frac, 0.0), 1.0)

            least_allocated = ((1 - cpu_frac) + (1 - ram_frac)) / 2 * 100
            balanced        = (1 - abs(cpu_frac - ram_frac)) * 100

            scores[node_id] = (least_allocated + balanced) / 2

        best_node = max(scores, key=lambda n: scores[n])
        return best_node, scores

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
            f"negative_usage_violations="
            f"{len(summary['negative_usage_violations'])}, "
            f"capacity_violations={len(summary['capacity_violations'])}"
        )
        for violation in summary["negative_usage_violations"][:5]:
            print(f"      negative usage: {violation}")
        for violation in summary["capacity_violations"][:5]:
            print(f"      capacity violation: {violation}")

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

    # ------------------------------------------------------------------ #
    #  Helpers                                                             #
    # ------------------------------------------------------------------ #

    def get_scheduling_report(self) -> str:
        """
        Return a human-readable summary of all binding decisions so far.
        """
        if not self._decisions:
            return "No scheduling decisions recorded."

        lines = [
            f"{'App':<28} {'Module':<36} {'Node':<18} {'Score':>6}  "
            f"{'CPU':>4}  {'RAM':>7}  {'BW':>6}  {'Class':<24} "
            f"{'p99':>6}  {'Dom':>7} {'Layers':<14} {'Chk':>3}",
            "-" * 166,
        ]
        for d in self._decisions:
            layers = ",".join(d.get("allowed_layers") or []) or "any"
            service_class = d.get("service_class") or "unknown"
            slo_ms_p99 = d.get("slo_ms_p99")
            slo_display = "n/a" if slo_ms_p99 is None else str(slo_ms_p99)
            lines.append(
                f"{d['app']:<28} {d['module']:<36} {d['node_name']:<18} "
                f"{d['score']:>6.2f}  {d['CPU_req']:>4}  "
                f"{d['RAM_req']:>7}  {d['BW_req']:>6}  "
                f"{service_class:<24} {slo_display:>6}  "
                f"{d['dominant_share']:>7.4f} {layers:<14} "
                f"{str(d.get('allowed_layers_considered', False)):>3}"
            )
        return "\n".join(lines)
