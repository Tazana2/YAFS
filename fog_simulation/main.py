"""Punto de entrada de la simulacion urbana multiaplicacion."""

import random
from pathlib import Path

import networkx as nx

from fog_simulation.topology           import create_edge_fog_cloud_topology
from fog_simulation.visualization      import visualize_topology, create_deployment_diagram
from fog_simulation.recording          import SimulationRecorder
from fog_simulation.simulation         import run_simulation
from fog_simulation.analysis           import (
    analyze_results,
    export_resource_usage_outputs,
    export_slo_outputs,
)


def main():
    random.seed(42)

    print("\n" + "=" * 70)
    print("  SIMULACION — CIUDAD INTELIGENTE MULTIAPP")
    print("  Video + Sensores + Servicios Compartidos Edge/Gateway/Fog/Cloud")
    print("=" * 70 + "\n")

    # ── 1. Topología ──────────────────────────────────────────────────
    print("Paso 1: Creando topologia multi-zona Edge/Gateway/Fog/Cloud...")
    topology, positions, nodes_info = create_edge_fog_cloud_topology(
        with_gateways=True,
        gateways_per_zone=1,
    )
    n_cameras = sum(1 for a in nodes_info.values() if a["type"] == "edge")
    n_gateways = sum(1 for a in nodes_info.values() if a["type"] == "gateway")
    n_fog     = sum(1 for a in nodes_info.values() if a["type"] == "fog")
    n_cloud   = sum(1 for a in nodes_info.values() if a["type"] == "cloud")
    print(f"   {n_cameras} nodos edge (video/sensores)")
    print(f"   {n_gateways} gateways de transito")
    print(f"   {n_fog} nodos fog (video/sensores/shared)")
    print(f"   {n_cloud} servicios cloud por rol")
    print(f"   {len(topology.G.edges())} enlaces de red\n")

    # ── 2. Exportar topología ─────────────────────────────────────────
    results_path = Path("results_fog_simulation")
    results_path.mkdir(exist_ok=True)

    print("Paso 2: Exportando topología...")
    nx.write_gexf(topology.G,    str(results_path / "fog_simulation_topology.gexf"))
    nx.write_graphml(topology.G, str(results_path / "fog_simulation_topology.graphml"))
    print("   Archivos exportados para Gephi/yEd\n")

    # ── 3. Visualizaciones ────────────────────────────────────────────
    print("Paso 3: Generando visualizaciones...")
    visualize_topology(
        topology, positions, nodes_info,
        save_path=str(results_path / "topology_fog_simulation.png"),
    )
    create_deployment_diagram(
        nodes_info,
        save_path=str(results_path / "deployment_diagram.png"),
    )

    # ── 4. Recorder ───────────────────────────────────────────────────
    print("\nPaso 4: Configurando grabación de la simulación...")
    recorder = SimulationRecorder(
        topology=topology,
        positions=positions,
        nodes_info=nodes_info,
        results_path=str(results_path),
        snapshot_interval=1000,
        fps=5,
    )
    print(f"   Recorder listo "
            f"(intervalo={recorder.snapshot_interval}, fps={recorder.fps})")

    # ── 5. Simulación ─────────────────────────────────────────────────
    print("\nPaso 5: Ejecutando simulación...")
    sim, results_path = run_simulation(topology, stop_time=50_000, recorder=recorder)

    # ── 5.1 Mapa de scheduling (pods por nodo) ───────────────────────
    print("\nPaso 5.1: Exportando mapa de scheduling (pods por nodo)...")
    pod_allocations = sim.get_alloc_entities()
    visualize_topology(
        topology,
        positions,
        nodes_info,
        save_path=str(results_path / "scheduling_pods_topology.png"),
        pod_allocations=pod_allocations,
        title_suffix="Estado final de scheduling (pods por nodo)",
    )

    # ── 5.2 Gráficas CPU/RAM por nodo ─────────────────────────────────
    print("\nPaso 5.2: Generando gráficas de uso CPU/RAM por nodo...")
    export_resource_usage_outputs(results_path, nodes_info)

    # ── 5.3 Reporte SLO/latencia ──────────────────────────────────────
    print("\nPaso 5.3: Generando reporte SLO/latencia...")
    export_slo_outputs(results_path, window_size=250, top_n=10)

    # ── 6. Video ──────────────────────────────────────────────────────
    print("\nPaso 6: Generando video de la simulación...")
    recorder.make_video(
        output_path=results_path / "simulation_video.mp4",
        fps=recorder.fps,
    )

    # ── 7. Análisis ───────────────────────────────────────────────────
    print("\nPaso 7: Analizando resultados...")
    analyze_results(results_path, nodes_info, export_resource_graphs=False)

    # ── Resumen ───────────────────────────────────────────────────────
    print("=" * 70)
    print("PROCESO COMPLETADO CON ÉXITO")
    print("=" * 70)
    print(f"\nResultados en: {results_path}/")
    print("\nArchivos generados:")
    print("   • topology_fog_simulation.png — Topologia de la red")
    print("   • scheduling_pods_topology.png — Topologia con pods por nodo")
    print("   • deployment_diagram.png  — Flujos A y B diferenciados")
    print("   • fog_simulation_topology.gexf   — Topologia (Gephi)")
    print("   • fog_simulation_topology.graphml— Topologia (GraphML)")
    print("   • sim_trace.csv           — Procesamiento de mensajes")
    print("   • sim_trace_link.csv      — Transmisiones de red")
    print("   • resource_usage/node_resource_usage_timeline.csv — Serie temporal CPU/RAM")
    print("   • cpu_usage/node_XX_*_cpu.png — Gráficas de CPU por nodo")
    print("   • ram_usage/node_XX_*_ram.png — Gráficas de RAM por nodo")
    print("   • slo_summary.csv       — Métricas p95/p99/jitter/SLO por servicio")
    print("   • slo_summary_window_250.csv — Métricas SLO por ventana")
    print("   • slo_report.html       — Reporte visual SLO/latencia")
    print("   • figures/*.png         — Gráficas p99, jitter, SLO y enlaces")
    print("   • simulation_video.mp4    — Video de la simulación")
    print()
    print("Aplicaciones simuladas:")
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
