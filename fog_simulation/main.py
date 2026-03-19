"""
Punto de entrada — Sistema de Parqueaderos con Visión Artificial.

Arquitectura
------------
  Cámara IP (edge)  →  Raspberry Pi 4 (fog / YOLOv8)  →  Cloud

Flujos simulados
----------------
  Flujo A (Inteligencia) : Cámara → YOLOv8_RPi4 → CloudRegistry (JSON).
                           Prioridad Media  |  Carga CPU Alta.
  Flujo B (Seguridad)    : Cámara → Passthrough → CloudVideoStorage.
                           Prioridad Alta   |  Carga Red Alta.

Ejecución
---------
    python -m fog_simulation
    # o bien
    python fog_simulation/main.py
"""

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
    print("  SIMULACIÓN — SISTEMA DE PARQUEADEROS CON VISIÓN ARTIFICIAL")
    print("  Cámaras IP  +  Raspberry Pi 4 (YOLOv8)  +  Cloud")
    print("=" * 70 + "\n")

    # ── 1. Topología ──────────────────────────────────────────────────
    print("🔧 Paso 1: Creando topología Cámara/RPi4/Cloud...")
    topology, positions, nodes_info = create_edge_fog_cloud_topology()
    n_cameras = sum(1 for a in nodes_info.values() if a["type"] == "edge")
    n_fog     = sum(1 for a in nodes_info.values() if a["type"] == "fog")
    n_cloud   = sum(1 for a in nodes_info.values() if a["type"] == "cloud")
    print(f"   ✓ {n_cameras} Cámaras IP 720p (edge)")
    print(f"   ✓ {n_fog} Raspberry Pi 4 con YOLOv8 (fog)")
    print(f"   ✓ {n_cloud} Servidores Cloud (JSON + Video Storage)")
    print(f"   ✓ {len(topology.G.edges())} enlaces de red\n")

    # ── 2. Exportar topología ─────────────────────────────────────────
    results_path = Path("results_parking")
    results_path.mkdir(exist_ok=True)

    print("🔧 Paso 2: Exportando topología...")
    nx.write_gexf(topology.G,    str(results_path / "parking_topology.gexf"))
    nx.write_graphml(topology.G, str(results_path / "parking_topology.graphml"))
    print("   ✓ Archivos exportados para Gephi/yEd\n")

    # ── 3. Visualizaciones ────────────────────────────────────────────
    print("🔧 Paso 3: Generando visualizaciones...")
    visualize_topology(
        topology, positions, nodes_info,
        save_path=str(results_path / "topology_parking.png"),
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
    print("   • topology_parking.png    — Topología de la red")
    print("   • deployment_diagram.png  — Flujos A y B diferenciados")
    print("   • parking_topology.gexf   — Topología (Gephi)")
    print("   • parking_topology.graphml— Topología (GraphML)")
    print("   • sim_trace.csv           — Procesamiento de mensajes")
    print("   • sim_trace_link.csv      — Transmisiones de red")
    print("   • simulation_video.mp4    — Video de la simulación")
    print()
    print("📌 Flujos simulados:")
    print("   Flujo A — Inteligencia : Cámara → YOLOv8 (RPi4) → CloudRegistry")
    print("             Prioridad Media | Carga CPU Alta (~450 ms/frame en RPi4)")
    print("   Flujo B — Seguridad    : Cámara → Passthrough (RPi4) → VideoStorage")
    print("             Prioridad Alta | Carga Red Alta (~500 KB/chunk)")

    print("   • sim_trace_link.csv           — Tráfico de red")
    print("   • frames/frame_NNNNN.png       — Frames de la simulación")
    print("   • simulation_video.mp4         — Video de evolución\n")


if __name__ == "__main__":
    main()
