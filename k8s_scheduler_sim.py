from yafs.placement import Placement

class KubernetesDefaultScheduler(Placement):
    """
    Simula el scheduler por defecto de Kubernetes (kube-scheduler).

    Fase 1 - Filtering:
      - NodeUnschedulable: descarta nodos cordoned
      - NodeResourcesFit: verifica CPU *y* RAM disponibles

    Fase 2 - Scoring (plugins con weight=1 c/u):
      - LeastAllocated:           score = (free_cpu% + free_ram%) / 2 * 100
      - BalancedResourceAlloc:    score = (1 - |cpu_frac - ram_frac|) * 100
      Final = promedio ponderado de ambos (weights iguales → promedio simple)

    Fase 3 - Binding:
      - deploy_module() en el nodo ganador
      - Actualiza CPU_used / RAM_used en el nodo (resource accounting)
    """

    def __init__(self, name):
        super(KubernetesDefaultScheduler, self).__init__(name)

    # ------------------------------------------------------------------ #
    #  Punto de entrada principal                                          #
    # ------------------------------------------------------------------ #

    def initial_allocation(self, sim, app_name):
        app = sim.apps[app_name]
        topology = sim.topology

        for module in app.modules:
            # --- Fase 1: Filtering ---
            candidates = self._filter_nodes(topology, module)

            if not candidates:
                print(
                    f"[K8s Scheduler] No feasible node for module "
                    f"'{module.get('name', module)}' — skipping."
                )
                continue

            # --- Fase 2: Scoring ---
            best_node = self._score_nodes(candidates, topology, module)

            # --- Fase 3: Binding ---
            sim.deploy_module(app_name, module["name"], [best_node])

            # Resource accounting: descuenta recursos en el nodo elegido
            # (equivale al resource reservation que hace K8s al hacer bind)
            node = topology.nodes[best_node]
            node["CPU_used"] = node.get("CPU_used", 0) + module.get("CPU_req", 0)
            node["RAM_used"] = node.get("RAM_used", 0) + module.get("RAM_req", 0)

    # ------------------------------------------------------------------ #
    #  Fase 1 – Filtering                                                  #
    # ------------------------------------------------------------------ #

    def _filter_nodes(self, topology, module):
        """
        Replica los Filter plugins del scheduler real:

        NodeUnschedulable  → salta nodos con unschedulable=True (cordoned)
        NodeResourcesFit   → el nodo debe tener suficiente CPU *y* RAM libres
        """
        cpu_req = module.get("CPU_req", 0)
        ram_req = module.get("RAM_req", 0)
        candidates = []

        for node_id in topology.nodes:
            node = topology.nodes[node_id]

            # Plugin: NodeUnschedulable
            if node.get("unschedulable", False):
                continue

            # Plugin: NodeResourcesFit  (CPU + RAM)
            cpu_free = node.get("CPU", 0) - node.get("CPU_used", 0)
            ram_free = node.get("RAM", 0) - node.get("RAM_used", 0)

            if cpu_free >= cpu_req and ram_free >= ram_req:
                candidates.append(node_id)

        return candidates

    # ------------------------------------------------------------------ #
    #  Fase 2 – Scoring                                                    #
    # ------------------------------------------------------------------ #

    def _score_nodes(self, candidates, topology, module):
        """
        Replica los Score plugins por defecto de K8s (ambos weight=1):

        LeastAllocated
            Favorece nodos con más recursos libres DESPUÉS de colocar el pod.
            score = ((1 - cpu_frac_post) + (1 - ram_frac_post)) / 2 * 100

        BalancedResourceAllocation
            Penaliza desequilibrio entre uso de CPU y RAM.
            score = (1 - |cpu_frac_post - ram_frac_post|) * 100

        Score final = promedio de ambos (pesos iguales en K8s por defecto).
        El nodo con mayor score gana.
        """
        cpu_req = module.get("CPU_req", 0)
        ram_req = module.get("RAM_req", 0)
        scores = {}

        for node_id in candidates:
            node = topology.nodes[node_id]

            cpu_cap = max(node.get("CPU", 1), 1)   # evita división por 0
            ram_cap = max(node.get("RAM", 1), 1)

            # Fracción de uso POST-asignación del módulo
            cpu_frac = (node.get("CPU_used", 0) + cpu_req) / cpu_cap
            ram_frac = (node.get("RAM_used", 0) + ram_req) / ram_cap

            # Plugin 1: LeastAllocated  (higher = more free resources)
            least_allocated = ((1 - cpu_frac) + (1 - ram_frac)) / 2 * 100

            # Plugin 2: BalancedResourceAllocation  (higher = more balanced)
            balanced = (1 - abs(cpu_frac - ram_frac)) * 100

            # Promedio ponderado (weight=1 para ambos plugins en K8s)
            scores[node_id] = (least_allocated + balanced) / 2

        return max(scores, key=lambda n: scores[n])