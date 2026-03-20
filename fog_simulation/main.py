"""Punto de entrada de la simulacion urbana multiaplicacion."""

import random
from pathlib import Path

import networkx as nx

from fog_simulation.topology           import create_edge_fog_cloud_topology
from fog_simulation.visualization      import visualize_topology, create_deployment_diagram
from fog_simulation.recording          import SimulationRecorder
from fog_simulation.simulation         import run_simulation
from fog_simulation.analysis           import analyze_results


def main():
    random.seed(42)

    print("\n" + "=" * 70)
    print("  SIMULACION — CIUDAD INTELIGENTE MULTIAPP")
    print("  Video + Sensores + Servicios Compartidos Edge/Fog/Cloud")
    print("=" * 70 + "\n")

    # ── 1. Topología ──────────────────────────────────────────────────
    print("🔧 Paso 1: Creando topologia multi-zona Edge/Fog/Cloud...")
    topology, positions, nodes_info = create_edge_fog_cloud_topology()
    n_cameras = sum(1 for a in nodes_info.values() if a["type"] == "edge")
    n_fog     = sum(1 for a in nodes_info.values() if a["type"] == "fog")
    n_cloud   = sum(1 for a in nodes_info.values() if a["type"] == "cloud")
    print(f"   ✓ {n_cameras} nodos edge (video/sensores)")
    print(f"   ✓ {n_fog} nodos fog (video/sensores/shared)")
    print(f"   ✓ {n_cloud} servicios cloud por rol")
    print(f"   ✓ {len(topology.G.edges())} enlaces de red\n")

    # ── 2. Exportar topología ─────────────────────────────────────────
    results_path = Path("results_smart_city")
    results_path.mkdir(exist_ok=True)

    print("🔧 Paso 2: Exportando topología...")
    nx.write_gexf(topology.G,    str(results_path / "smart_city_topology.gexf"))
    nx.write_graphml(topology.G, str(results_path / "smart_city_topology.graphml"))
    print("   ✓ Archivos exportados para Gephi/yEd\n")

    # ── 3. Visualizaciones ────────────────────────────────────────────
    print("🔧 Paso 3: Generando visualizaciones...")
    visualize_topology(
        topology, positions, nodes_info,
        save_path=str(results_path / "topology_smart_city.png"),
    )
    create_deployment_diagram(
        nodes_info,
        save_path=str(results_path / "deployment_diagram.png"),
    )

    # ── 4. Recorder ───────────────────────────────────────────────────
    print("\n🔧 Paso 4: Configurando grabación de la simulación...")
    recorder = SimulationRecorder(
        topology=topology,
        positions=positions,
        nodes_info=nodes_info,
        results_path=str(results_path),
        snapshot_interval=1000,
        fps=5,
    )
    print(f"   ✓ Recorder listo "
          f"(intervalo={recorder.snapshot_interval}, fps={recorder.fps})")

    # ── 5. Simulación ─────────────────────────────────────────────────
    print("\n🔧 Paso 5: Ejecutando simulación...")
    sim, results_path = run_simulation(topology, stop_time=50_000, recorder=recorder)

    # ── 6. Video ──────────────────────────────────────────────────────
    print("\n🔧 Paso 6: Generando video de la simulación...")
    recorder.make_video(
        output_path=results_path / "simulation_video.mp4",
        fps=recorder.fps,
    )

    # ── 7. Análisis ───────────────────────────────────────────────────
    print("\n🔧 Paso 7: Analizando resultados...")
    analyze_results(results_path, nodes_info)

    # ── Resumen ───────────────────────────────────────────────────────
    print("=" * 70)
    print("✅ PROCESO COMPLETADO CON ÉXITO")
    print("=" * 70)
    print(f"\n📁 Resultados en: {results_path}/")
    print("\n📄 Archivos generados:")
    print("   • topology_smart_city.png — Topologia de la red")
    print("   • deployment_diagram.png  — Flujos A y B diferenciados")
    print("   • smart_city_topology.gexf   — Topologia (Gephi)")
    print("   • smart_city_topology.graphml— Topologia (GraphML)")
    print("   • sim_trace.csv           — Procesamiento de mensajes")
    print("   • sim_trace_link.csv      — Transmisiones de red")
    print("   • simulation_video.mp4    — Video de la simulación")
    print()
    print("📌 Aplicaciones simuladas:")
    print("   App 1 — Urban_Video_Analytics")
    print("           edge-video-ingestion → edge-inference → tracking/event → stream-processing")
    print("   App 2 — Urban_Sensor_Climatology")
    print("           edge-sensor-ingestion → preprocessing → stream-processing → prediction")
    print("   Shared — Platform_Lifecycle")
    print("            simulation-service → mlops → deployment → api/access → observability")

    print("   • sim_trace_link.csv           — Tráfico de red")
    print("   • frames/frame_NNNNN.png       — Frames de la simulación")
    print("   • simulation_video.mp4         — Video de evolución\n")


if __name__ == "__main__":
    main()
