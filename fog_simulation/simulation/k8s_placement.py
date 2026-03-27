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

from yafs.placement import Placement
from yafs.application import Application


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

    def __init__(self, name, verbose: bool = True):
        super().__init__(name)
        self.verbose = verbose
        self._decisions: list[dict] = []   # log of all binding decisions
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

        for module_name, services in app.services.items():
            attrs     = module_attrs.get(module_name, {})
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

            # Build a lightweight "pod spec" for filter/score
            pod = {
                "name":    module_name,
                "CPU_req": attrs.get("CPU_req", 0),
                "RAM_req": attrs.get("RAM_req", 0),
            }

            # ── Phase 1: Filtering ────────────────────────────────────────
            candidates = self._filter_nodes(topology, pod)

            if not candidates:
                print(
                    f"  [K8s Scheduler] WARNING — no feasible node for "
                    f"'{module_name}' in '{app_name}'. Module not deployed."
                )
                skipped += 1
                continue

            # ── Phase 2: Scoring ──────────────────────────────────────────
            best_node, scores = self._score_nodes(candidates, topology, pod)

            # ── Phase 3: Binding ──────────────────────────────────────────
            sim.deploy_module(app_name, module_name, services, [best_node])

            # Resource accounting — deduct from node's available capacity
            node_attrs = topology.G.nodes[best_node]
            node_attrs["CPU_used"] = node_attrs.get("CPU_used", 0) + pod["CPU_req"]
            node_attrs["RAM_used"] = node_attrs.get("RAM_used", 0) + pod["RAM_req"]

            # Record decision
            decision = {
                "app":       app_name,
                "module":    module_name,
                "node_id":   best_node,
                "node_name": node_attrs.get("name", str(best_node)),
                "score":     round(scores[best_node], 2),
                "CPU_req":   pod["CPU_req"],
                "RAM_req":   pod["RAM_req"],
            }
            self._decisions.append(decision)
            scheduled += 1

            if self.verbose:
                print(
                    f"  [bind] {module_name:45s} → {decision['node_name']:20s} "
                    f"score={decision['score']:6.2f}  "
                    f"CPU+{pod['CPU_req']}  RAM+{pod['RAM_req']}MB"
                )

        if self.verbose:
            print(
                f"  → {scheduled} module(s) bound, {skipped} source/sink(s) skipped.\n"
            )

    # ------------------------------------------------------------------ #
    #  Phase 1 — Filtering                                                 #
    # ------------------------------------------------------------------ #

    def _filter_nodes(self, topology, pod: dict) -> list:
        """
        Return candidate node IDs that pass all filter plugins.

        Plugins implemented
        -------------------
        NodeUnschedulable  — skips nodes where ``unschedulable=True``.
        NodeResourcesFit   — requires ``free_cpu >= CPU_req`` AND
                             ``free_ram >= RAM_req``.
        """
        cpu_req = pod["CPU_req"]
        ram_req = pod["RAM_req"]
        candidates = []

        for node_id in topology.G.nodes:
            node = topology.G.nodes[node_id]

            # Gateways are transit-only network nodes and must never host modules.
            if node.get("type") == "gateway":
                continue

            # Plugin: NodeUnschedulable
            if node.get("unschedulable", False):
                continue

            # Plugin: NodeResourcesFit
            cpu_free = node.get("CPU", 0) - node.get("CPU_used", 0)
            ram_free = node.get("RAM", 0) - node.get("RAM_used", 0)

            if cpu_free >= cpu_req and ram_free >= ram_req:
                candidates.append(node_id)

        return candidates

    # ------------------------------------------------------------------ #
    #  Phase 2 — Scoring                                                   #
    # ------------------------------------------------------------------ #

    def _score_nodes(
        self, candidates: list, topology, pod: dict
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
            node = topology.G.nodes[node_id]

            cpu_cap = max(node.get("CPU", 1), 1)   # guard against 0-capacity nodes
            ram_cap = max(node.get("RAM", 1), 1)

            cpu_frac = (node.get("CPU_used", 0) + cpu_req) / cpu_cap
            ram_frac = (node.get("RAM_used", 0) + ram_req) / ram_cap

            # Clamp fractions to [0, 1] for numerical safety
            cpu_frac = min(max(cpu_frac, 0.0), 1.0)
            ram_frac = min(max(ram_frac, 0.0), 1.0)

            least_allocated = ((1 - cpu_frac) + (1 - ram_frac)) / 2 * 100
            balanced        = (1 - abs(cpu_frac - ram_frac)) * 100

            scores[node_id] = (least_allocated + balanced) / 2

        best_node = max(scores, key=lambda n: scores[n])
        return best_node, scores

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
            f"{'Module':<45} {'Node':<20} {'Score':>6}  {'CPU':>4}  {'RAM (MB)':>9}",
            "-" * 90,
        ]
        for d in self._decisions:
            lines.append(
                f"{d['module']:<45} {d['node_name']:<20} "
                f"{d['score']:>6.2f}  {d['CPU_req']:>4}  {d['RAM_req']:>9}"
            )
        return "\n".join(lines)
