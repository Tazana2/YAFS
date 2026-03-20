"""Orquestador de simulacion para aplicaciones urbanas multi-servicio."""

from pathlib import Path

from yafs.core import Sim
from yafs.placement import JSONPlacement
from yafs.path_routing import DeviceSpeedAwareRouting
from yafs.distribution import deterministic_distribution

from fog_simulation.applications import (
    create_platform_lifecycle_app,
    create_sensor_climatology_app,
    create_video_analytics_app,
)


def _nodes_by_role(topology):
    nodes = list(topology.G.nodes(data=True))
    edge_video = [n for n, a in nodes if a.get("type") == "edge" and a.get("role") == "video_ingestion"]
    edge_sensor = [n for n, a in nodes if a.get("type") == "edge" and a.get("role") == "sensor_ingestion"]
    fog_video = [n for n, a in nodes if a.get("type") == "fog" and a.get("role") == "video_processing"]
    fog_sensor = [n for n, a in nodes if a.get("type") == "fog" and a.get("role") == "sensor_processing"]
    fog_shared = [n for n, a in nodes if a.get("type") == "fog" and a.get("role") == "shared_processing"]
    cloud = {a.get("role"): n for n, a in nodes if a.get("type") == "cloud"}
    return edge_video, edge_sensor, fog_video, fog_sensor, fog_shared, cloud


def _alloc(app_name, module_name, node_ids):
    return [
        {
            "app": app_name,
            "module_name": module_name,
            "id_resource": node_id,
        }
        for node_id in node_ids
    ]


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
    print("INICIANDO SIMULACION — ESCENARIO URBANO MULTIAPP")
    print("=" * 70)

    results_path = Path("results_smart_city")
    results_path.mkdir(exist_ok=True)

    app_video = create_video_analytics_app()
    app_sensor = create_sensor_climatology_app()
    app_platform = create_platform_lifecycle_app()

    edge_video, edge_sensor, fog_video, fog_sensor, fog_shared, cloud = _nodes_by_role(topology)

    placement_video = {
        "initialAllocation": (
            _alloc(app_video.name, "edge-inference-service", fog_video)
            + _alloc(app_video.name, "tracking-and-event-service", fog_video)
            + _alloc(app_video.name, "video-stream-processing-service", fog_shared)
            + _alloc(app_video.name, "storage-service", [cloud["storage"]])
            + _alloc(app_video.name, "api-and-access-service", [cloud["api_access"]])
        )
    }

    placement_sensor = {
        "initialAllocation": (
            _alloc(app_sensor.name, "edge-sensor-preprocessing-service", fog_sensor)
            + _alloc(app_sensor.name, "sensor-stream-processing-service", fog_sensor)
            + _alloc(app_sensor.name, "sensor-prediction-service", fog_shared)
            + _alloc(app_sensor.name, "storage-service", [cloud["storage"]])
            + _alloc(app_sensor.name, "api-and-access-service", [cloud["api_access"]])
        )
    }

    placement_platform = {
        "initialAllocation": (
            _alloc(app_platform.name, "mlops-platform-service", [cloud["mlops"]])
            + _alloc(app_platform.name, "deployment-and-distribution-service", [cloud["deployment"]])
            + _alloc(app_platform.name, "api-and-access-service", [cloud["api_access"]])
        )
    }

    p_video = JSONPlacement(name="Placement_Video", json=placement_video)
    p_sensor = JSONPlacement(name="Placement_Sensor", json=placement_sensor)
    p_platform = JSONPlacement(name="Placement_Platform", json=placement_platform)

    selector = DeviceSpeedAwareRouting()

    # ── Simulador ─────────────────────────────────────────────────────────
    sim = Sim(topology, default_results_path=str(results_path / "sim_trace"))

    print("\nDesplegando aplicaciones...")
    sim.deploy_app(app_video, p_video, selector)
    sim.deploy_app(app_sensor, p_sensor, selector)
    sim.deploy_app(app_platform, p_platform, selector)

    # Sinks puros: se despliegan explicitamente para que puedan recibir mensajes.
    sim.deploy_sink(app_video.name, cloud["visualization"], "visualization-service")
    sim.deploy_sink(app_video.name, cloud["notification"], "notification-service")
    sim.deploy_sink(app_video.name, cloud["observability"], "observability-service")

    sim.deploy_sink(app_sensor.name, cloud["visualization"], "visualization-service")
    sim.deploy_sink(app_sensor.name, cloud["notification"], "notification-service")
    sim.deploy_sink(app_sensor.name, cloud["observability"], "observability-service")

    sim.deploy_sink(app_platform.name, cloud["observability"], "observability-service")

    print("✓ App 1 (Urban_Video_Analytics) desplegada")
    print("✓ App 2 (Urban_Sensor_Climatology) desplegada")
    print("✓ Servicios de plataforma (Platform_Lifecycle) desplegados")

    # ── Fuentes: cámaras IP ───────────────────────────────────────────────
    print("\nDesplegando fuentes de carga...")

    for cam_id in edge_video:
        msg = app_video.get_message("M.Video.Batch")
        dist = deterministic_distribution(1200, name=f"VideoSource_{cam_id}")
        sim.deploy_source(app_video.name, id_node=cam_id, msg=msg, distribution=dist)

    for sensor_id in edge_sensor:
        msg = app_sensor.get_message("M.Sensor.Batch.Raw")
        dist = deterministic_distribution(1000, name=f"SensorSource_{sensor_id}")
        sim.deploy_source(app_sensor.name, id_node=sensor_id, msg=msg, distribution=dist)

    climate_src_node = fog_shared[0] if fog_shared else fog_sensor[0]
    sim.deploy_source(
        app_sensor.name,
        id_node=climate_src_node,
        msg=app_sensor.get_message("M.Climate.Sync"),
        distribution=deterministic_distribution(30000, name="ClimateSync"),
    )

    sim.deploy_source(
        app_platform.name,
        id_node=cloud["mlops"],
        msg=app_platform.get_message("M.Platform.TrainingBatch"),
        distribution=deterministic_distribution(20000, name="PlatformTraining"),
    )

    print(f"✓ {len(edge_video)} fuentes de video desplegadas")
    print(f"✓ {len(edge_sensor)} fuentes de sensores desplegadas")
    print("✓ Fuente periodica de climatologia y ciclo MLOps desplegada")

    # ── Recorder ──────────────────────────────────────────────────────────
    if recorder is not None:
        recorder.set_csv_paths(str(results_path / "sim_trace"))
        recorder.sim_until = stop_time
        sim.env.process(recorder.snapshot_generator(sim))
        total_frames = stop_time // recorder.snapshot_interval
        print(f"\n📷 Grabación activada: ~{total_frames} frames "
              f"(intervalo={recorder.snapshot_interval})")

    # ── Ejecución ─────────────────────────────────────────────────────────
    print(f"\nTiempo de simulacion: {stop_time:,} ut  (≈ {stop_time/1000:.0f} s reales)")
    print("-" * 70)
    sim.run(stop_time)

    if recorder is not None:
        recorder.capture_frame(stop_time, sim)
        print(f"   📷 Frame final capturado  [t={stop_time}]")

    print("\n" + "=" * 70)
    print("SIMULACION COMPLETADA")
    print("=" * 70 + "\n")

    return sim, results_path
