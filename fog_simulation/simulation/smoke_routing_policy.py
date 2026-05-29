"""Smoke checks for hop-count and latency-aware routing policies.

Run with:
    python -m fog_simulation.simulation.smoke_routing_policy
"""

from types import SimpleNamespace

import networkx as nx

from yafs.application import Message
from yafs.path_routing import DeviceSpeedAwareRouting, LatencyAwareRouting
from yafs.topology import Topology


def _make_sim():
    topology = Topology()
    graph = nx.DiGraph()
    graph.add_node(0)
    graph.add_node(1)
    graph.add_node(3)
    graph.add_edge(0, 3, BW=1000, PR=100)
    graph.add_edge(0, 1, BW=1000, PR=1)
    graph.add_edge(1, 3, BW=1000, PR=1)
    topology.G = graph
    return SimpleNamespace(topology=topology)


def main() -> None:
    sim = _make_sim()
    message = Message("M", "Src", "Dst", bytes=1000)
    alloc_des = {10: 3}
    alloc_module = {"App": {"Dst": [10]}}

    hop_paths, _hop_des = DeviceSpeedAwareRouting().get_path(
        sim, "App", message, 0, alloc_des, alloc_module, {}, from_des=0
    )
    latency_paths, _latency_des = LatencyAwareRouting().get_path(
        sim, "App", message, 0, alloc_des, alloc_module, {}, from_des=0
    )

    assert hop_paths == [[0, 3]]
    assert latency_paths == [[0, 1, 3]]

    print("Routing policy smoke checks passed.")


if __name__ == "__main__":
    main()
