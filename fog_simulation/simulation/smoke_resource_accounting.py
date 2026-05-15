"""Smoke checks for ResourceAccounting.

Run with:
    python -m fog_simulation.simulation.smoke_resource_accounting
"""

import networkx as nx

from yafs.topology import Topology

from fog_simulation.simulation.resource_accounting import ResourceAccounting


def _make_topology() -> Topology:
    topology = Topology()
    graph = nx.DiGraph()
    graph.add_node(
        0,
        name="edge-0",
        type="edge",
        role="sensor_ingestion",
        CPU=4,
        RAM=4096,
        BW=100,
    )
    graph.add_node(
        1,
        name="fog-0",
        type="fog",
        role="sensor_processing",
        CPU=8,
        RAM=8192,
        BW=200,
    )
    graph.add_edge(0, 1, BW=100, PR=1)
    graph.add_edge(1, 0, BW=100, PR=1)
    topology.G = graph
    return topology


def main() -> None:
    accounting = ResourceAccounting(_make_topology())
    profile = {
        "CPU_req": 2,
        "RAM_req": 1024,
        "BW_req": 20,
        "allowed_layers": ["edge", "fog"],
    }

    assert accounting.can_fit(0, profile)
    assert not accounting.can_fit(0, {**profile, "CPU_req": 5})
    assert not accounting.can_fit(0, {**profile, "RAM_req": 5000})
    assert not accounting.can_fit(0, {**profile, "BW_req": 120})

    accounting.commit(0, "SmokeApp", "Worker", profile)
    assert accounting.node_usage(0) == {"CPU": 2.0, "RAM": 1024.0, "BW": 20.0}

    accounting.release(0, "SmokeApp", "Worker", profile)
    assert accounting.node_usage(0) == {"CPU": 0.0, "RAM": 0.0, "BW": 0.0}

    accounting.commit(0, "SmokeApp", "Worker", profile)
    accounting.move("SmokeApp", "Worker", 0, 1, profile)
    assert accounting.node_usage(0) == {"CPU": 0.0, "RAM": 0.0, "BW": 0.0}
    assert accounting.node_usage(1) == {"CPU": 2.0, "RAM": 1024.0, "BW": 20.0}

    assert accounting.validate_no_negative_usage()
    assert accounting.validate_capacity_constraints()

    print("ResourceAccounting smoke checks passed.")


if __name__ == "__main__":
    main()
