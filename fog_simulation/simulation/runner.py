"""
Orquestador de la simulación — Sistema de Parqueaderos.

Responsabilidades
-----------------
1. Instanciar los dos flujos independientes:
     • Flujo A (Parking_Intelligence) — Cámara → YOLOv8 → CloudRegistry.
     • Flujo B (Parking_Security)     — Cámara → Passthrough → CloudVideoStorage.
2. Registrar los placements en los nodos correctos.
3. Desplegar fuentes (cámaras) con frecuencias realistas.
4. Ejecutar la simulación y devolver los resultados.

Nodos de referencia (topology/network.py)
-----------------------------------------
  0 – 5  : Cámaras IP (edge) — fuentes de ambos flujos
  6 – 8  : Raspberry Pi 4   (fog) — procesamiento / passthrough
  9 – 10 : Servidores Cloud        — sinks

Frecuencias de source (en unidades de tiempo simuladas, 1 ut ≈ 1 ms)
---------------------------------------------------------------------
  Flujo A : 1 frame de inferencia cada 2 000 ut (~2 fps efectivos,
            limitado por la latencia YOLOv8n = 450 ms).
  Flujo B : 1 chunk de 1 s de video cada 1 000 ut (stream continuo).
"""

from pathlib import Path

from yafs.core import Sim
from yafs.placement import JSONPlacement
from yafs.path_routing import DeviceSpeedAwareRouting
from yafs.distribution import deterministic_distribution

from fog_simulation.applications import (
    create_parking_intelligence_app,
    create_parking_security_app,
)

# Nodos fog (Raspberry Pi 4) y cámaras
CAMERA_NODES = list(range(6))          # 0 – 5
FOG_NODES    = [6, 7, 8]               # RPi4


def run_simulation(topology, stop_time: int = 50_000, recorder=None):
    """
    Orquesta y ejecuta la simulación de parqueaderos.

    Parameters
    ----------
    topology  : Topology de YAFS.
    stop_time : tiempo total en unidades simuladas (1 ut ≈ 1 ms).
    recorder  : instancia de SimulationRecorder (opcional).

    Returns
    -------
    sim          : objeto Sim tras la ejecución.
    results_path : Path al directorio de resultados.
    """
    print("\n" + "=" * 70)
    print("INICIANDO SIMULACIÓN — SISTEMA DE PARQUEADEROS")
    print("=" * 70)

    results_path = Path("results_parking")
    results_path.mkdir(exist_ok=True)

    # ── Aplicaciones ──────────────────────────────────────────────────────
    app_intelligence = create_parking_intelligence_app()   # Flujo A
    app_security     = create_parking_security_app()       # Flujo B

    # ── Placements ────────────────────────────────────────────────────────
    # Flujo A: YOLOv8_Inference se despliega en cada RPi4.
    placement_intelligence = {
        "initialAllocation": [
            {"app": "Parking_Intelligence",
             "module_name": "YOLOv8_Inference",
             "id_resource": rpi}
            for rpi in FOG_NODES
        ]
    }

    # Flujo B: VideoPassthrough se despliega en cada RPi4.
    placement_security = {
        "initialAllocation": [
            {"app": "Parking_Security",
             "module_name": "VideoPassthrough",
             "id_resource": rpi}
            for rpi in FOG_NODES
        ]
    }

    p1 = JSONPlacement(name="Placement_Intelligence", json=placement_intelligence)
    p2 = JSONPlacement(name="Placement_Security",     json=placement_security)

    selector = DeviceSpeedAwareRouting()

    # ── Simulador ─────────────────────────────────────────────────────────
    sim = Sim(topology, default_results_path=str(results_path / "sim_trace"))

    print("\nDesplegando aplicaciones...")
    sim.deploy_app(app_intelligence, p1, selector)
    sim.deploy_app(app_security,     p2, selector)
    print("✓ Flujo A (Parking_Intelligence) desplegado: Cámara→YOLOv8→CloudRegistry")
    print("✓ Flujo B (Parking_Security)     desplegado: Cámara→Passthrough→VideoStorage")

    # ── Fuentes: cámaras IP ───────────────────────────────────────────────
    print("\nDesplegando fuentes (cámaras IP)...")

    # Flujo A — 1 frame de inferencia cada 2 000 ut por cámara (~2 fps)
    for cam_id in CAMERA_NODES:
        msg  = app_intelligence.get_message("M.VideoFrame")
        dist = deterministic_distribution(2000, name=f"Cam_Intel_{cam_id}")
        sim.deploy_source(app_intelligence.name, id_node=cam_id,
                          msg=msg, distribution=dist)

    print(f"✓ {len(CAMERA_NODES)} fuentes Flujo A (inferencia, 2 fps)")

    # Flujo B — 1 chunk de 1 s de video cada 1 000 ut por cámara
    for cam_id in CAMERA_NODES:
        msg  = app_security.get_message("M.VideoChunk")
        dist = deterministic_distribution(1000, name=f"Cam_Sec_{cam_id}")
        sim.deploy_source(app_security.name, id_node=cam_id,
                          msg=msg, distribution=dist)

    print(f"✓ {len(CAMERA_NODES)} fuentes Flujo B (video continuo, 1 chunk/s)")

    # ── Recorder ──────────────────────────────────────────────────────────
    if recorder is not None:
        recorder.set_csv_paths(str(results_path / "sim_trace"))
        recorder.sim_until = stop_time
        sim.env.process(recorder.snapshot_generator(sim))
        total_frames = stop_time // recorder.snapshot_interval
        print(f"\n📷 Grabación activada: ~{total_frames} frames "
              f"(intervalo={recorder.snapshot_interval})")

    # ── Ejecución ─────────────────────────────────────────────────────────
    print(f"\nTiempo de simulación: {stop_time:,} ut  (≈ {stop_time/1000:.0f} s reales)")
    print("-" * 70)
    sim.run(stop_time)

    if recorder is not None:
        recorder.capture_frame(stop_time, sim)
        print(f"   📷 Frame final capturado  [t={stop_time}]")

    print("\n" + "=" * 70)
    print("SIMULACIÓN COMPLETADA")
    print("=" * 70 + "\n")

    return sim, results_path
