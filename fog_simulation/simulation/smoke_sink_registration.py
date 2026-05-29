"""Smoke checks for multi-sink registration and sink service time.

Run with:
    python -m fog_simulation.simulation.smoke_sink_registration
"""

import csv
import tempfile
from pathlib import Path

import networkx as nx

from yafs.application import Application, Message, fractional_selectivity
from yafs.core import Sim
from yafs.distribution import deterministic_distribution
from yafs.path_routing import DeviceSpeedAwareRouting
from yafs.placement import NoPlacementOfModules
from yafs.topology import Topology


def _make_topology() -> Topology:
    topology = Topology()
    graph = nx.DiGraph()
    for node_id in range(4):
        graph.add_node(node_id, IPT=1000, model=f"n-{node_id}", type="test")
    for src, dst in [(0, 1), (1, 2), (1, 3)]:
        graph.add_edge(src, dst, BW=100, PR=0)
        graph.add_edge(dst, src, BW=100, PR=0)
    topology.G = graph
    return topology


def _make_app() -> tuple[Application, Message]:
    app = Application("MultiSinkSmoke")
    app.set_modules(
        [
            {"source": {"Type": Application.TYPE_SOURCE}},
            {"processor": {"Type": Application.TYPE_MODULE, "RAM": 1}},
            {"sink-a": {"Type": Application.TYPE_SINK}},
            {"sink-b": {"Type": Application.TYPE_SINK}},
        ]
    )

    m_in = Message("M.In", "source", "processor", instructions=1000, bytes=1)
    m_a = Message("M.ToA", "processor", "sink-a", instructions=9000, bytes=1)
    m_b = Message("M.ToB", "processor", "sink-b", instructions=9000, bytes=1)

    app.add_source_messages(m_in)
    app.add_service_module("processor", m_in, m_a, fractional_selectivity, threshold=1.0)
    app.add_service_module("processor", m_in, m_b, fractional_selectivity, threshold=1.0)
    return app, m_in


def main() -> None:
    topology = _make_topology()
    app, source_message = _make_app()

    assert set(app.get_sink_modules()) == {"sink-a", "sink-b"}
    assert "sink-a" not in app.get_pure_modules()
    assert "sink-b" not in app.get_pure_modules()

    with tempfile.TemporaryDirectory(prefix="yafs_sink_smoke_") as tmpdir:
        result_base = str(Path(tmpdir) / "trace")
        sim = Sim(topology, default_results_path=result_base)
        sim.deploy_app(
            app,
            NoPlacementOfModules(name="manual"),
            DeviceSpeedAwareRouting(),
        )
        sim.deploy_module(app.name, "processor", app.services["processor"], [1])
        sim.deploy_sink(app.name, node=2, module="sink-a")
        sim.deploy_sink(app.name, node=3, module="sink-b")
        sim.deploy_source(
            app.name,
            id_node=0,
            msg=source_message,
            distribution=deterministic_distribution(name="source", time=1),
        )
        sim.run(until=10)

        with open(result_base + ".csv", newline="") as fh:
            rows = list(csv.DictReader(fh))

    sink_rows = [row for row in rows if row["module"] in {"sink-a", "sink-b"}]
    assert {row["module"] for row in sink_rows} == {"sink-a", "sink-b"}
    assert all(float(row["service"]) == 0.0 for row in sink_rows)

    print("Sink registration smoke checks passed.")


if __name__ == "__main__":
    main()
