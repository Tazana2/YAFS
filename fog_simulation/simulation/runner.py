"""Orquestador de simulacion para aplicaciones urbanas multi-servicio.

La colocacion de modulos de servicio (TYPE_MODULE) se delega al
KubernetesDefaultScheduler, que replica la logica Filter→Score→Bind del
kube-scheduler por defecto.  Las fuentes puras (camaras, sensores) y los
sinks (cloud) se siguen anclando explicitamente al nodo fisico correspondiente
— igual que DaemonSets y managed-services en un cluster Kubernetes real.
"""

from pathlib import Path

from yafs.core import Sim
from yafs.path_routing import DeviceSpeedAwareRouting
from yafs.distribution import exponential_distribution

from fog_simulation.applications import (
    create_platform_lifecycle_app,
    create_sensor_climatology_app,
    create_video_analytics_app,
)
from fog_simulation.simulation.k8s_placement import KubernetesDefaultScheduler


def _nodes_by_role(topology):
    nodes = list(topology.G.nodes(data=True))
    edge_video  = [n for n, a in nodes if a.get("type") == "edge"  and a.get("role") == "video_ingestion"]
    edge_sensor = [n for n, a in nodes if a.get("type") == "edge"  and a.get("role") == "sensor_ingestion"]
    fog_video   = [n for n, a in nodes if a.get("type") == "fog"   and a.get("role") == "video_processing"]
    fog_sensor  = [n for n, a in nodes if a.get("type") == "fog"   and a.get("role") == "sensor_processing"]
    fog_shared  = [n for n, a in nodes if a.get("type") == "fog"   and a.get("role") == "shared_processing"]

    cloud_nodes = [n for n, a in nodes if a.get("type") == "cloud"]
    cloud = {a.get("role"): n for n, a in nodes if a.get("type") == "cloud"}

    if cloud_nodes:
        default_cloud = cloud_nodes[0]
        for role in ["storage", "api_access", "visualization", "notification", "observability", "mlops", "deployment"]:
            cloud.setdefault(role, default_cloud)

    return edge_video, edge_sensor, fog_video, fog_sensor, fog_shared, cloud


def run_simulation(topology, stop_time: int = 50_000, recorder=None):
    """
    Orquesta y ejecuta la simulacion de parqueaderos.

    Los modulos de servicio son colocados automaticamente por
    KubernetesDefaultScheduler (Filter → Score → Bind).

    Parameters
    ----------
    topology  : Topology de YAFS.
    stop_time : tiempo total en unidades simuladas (1 ut ≈ 1 ms).
    recorder  : instancia de SimulationRecorder (opcional).

    Returns
    -------
    sim          : objeto Sim tras la ejecucion.
    results_path : Path al directorio de resultados.
    """
    print("\n" + "=" * 70)
    has_gateway = any(a.get("type") == "gateway" for _, a in topology.G.nodes(data=True))
    topo_label = "Edge/Gateway/Fog/Cloud" if has_gateway else "Edge/Fog/Cloud"

    print("INICIANDO SIMULACION — ESCENARIO URBANO MULTIAPP")
    print("  Placement: KubernetesDefaultScheduler (Filter → Score → Bind)")
    print(f"  Topologia: {topo_label}")
    print("=" * 70)

    results_path = Path("results_fog_simulation")
    results_path.mkdir(exist_ok=True)

    # ── Aplicaciones ──────────────────────────────────────────────────────
    app_video    = create_video_analytics_app()
    app_sensor   = create_sensor_climatology_app()
    app_platform = create_platform_lifecycle_app()

    edge_video, edge_sensor, fog_video, fog_sensor, fog_shared, cloud = (
        _nodes_by_role(topology)
    )

    # ── Scheduler K8s compartido para todo el cluster ─────────────────────
    # Un unico scheduler para las tres apps garantiza que el resource
    # accounting sea global: lo que consume App1 no esta disponible para App2.
    k8s_scheduler = KubernetesDefaultScheduler(
        name="K8s_Cluster_Scheduler",
        verbose=True,
    )

    selector = DeviceSpeedAwareRouting()

    # ── Simulador ─────────────────────────────────────────────────────────
    sim = Sim(topology, default_results_path=str(results_path / "sim_trace"))

    print("\nDesplegando aplicaciones con K8s scheduler...")
    sim.deploy_app(app_platform, k8s_scheduler, selector)
    sim.deploy_app(app_video,    k8s_scheduler, selector)
    sim.deploy_app(app_sensor,   k8s_scheduler, selector)

    # ── Sinks: always pinned to their cloud node (managed services) ────────
    sim.deploy_sink(app_video.name,    cloud["visualization"],  "visualization-service")
    sim.deploy_sink(app_video.name,    cloud["notification"],   "notification-service")
    sim.deploy_sink(app_video.name,    cloud["observability"],  "observability-service")

    sim.deploy_sink(app_sensor.name,   cloud["visualization"],  "visualization-service")
    sim.deploy_sink(app_sensor.name,   cloud["notification"],   "notification-service")
    sim.deploy_sink(app_sensor.name,   cloud["observability"],  "observability-service")

    sim.deploy_sink(app_platform.name, cloud["observability"],  "observability-service")

    print("✓ App 1 (Urban_Video_Analytics)     desplegada")
    print("✓ App 2 (Urban_Sensor_Climatology)  desplegada")
    print("✓ Servicios de plataforma (Platform_Lifecycle) desplegados")
    print("  (Las decisiones de scheduling se ejecutan al inicio de sim.run())")

    # ── Fuentes: camaras IP (pinned a su nodo fisico) ─────────────────────
    print("\nDesplegando fuentes de carga...")

    for cam_id in edge_video:
        msg  = app_video.get_message("M.Video.Batch")
        dist = exponential_distribution(lambd=1200, seed=1000 + cam_id, name=f"VideoSource_{cam_id}")
        sim.deploy_source(app_video.name, id_node=cam_id, msg=msg, distribution=dist)

    for sensor_id in edge_sensor:
        msg  = app_sensor.get_message("M.Sensor.Batch.Raw")
        dist = exponential_distribution(lambd=1000, seed=2000 + sensor_id, name=f"SensorSource_{sensor_id}")
        sim.deploy_source(app_sensor.name, id_node=sensor_id, msg=msg, distribution=dist)

    climate_src_node = fog_shared[0] if fog_shared else fog_sensor[0]
    sim.deploy_source(
        app_sensor.name,
        id_node=climate_src_node,
        msg=app_sensor.get_message("M.Climate.Sync"),
        distribution=exponential_distribution(lambd=30000, seed=3001, name="ClimateSync"),
    )

    sim.deploy_source(
        app_platform.name,
        id_node=cloud["mlops"],
        msg=app_platform.get_message("M.Platform.TrainingBatch"),
        distribution=exponential_distribution(lambd=20000, seed=4001, name="PlatformTraining"),
    )

    print(f"✓ {len(edge_video)}  fuentes de video desplegadas")
    print(f"✓ {len(edge_sensor)} fuentes de sensores desplegadas")
    print("✓ Fuentes de climatologia y ciclo MLOps desplegadas")

    # ── Recorder ──────────────────────────────────────────────────────────
    if recorder is not None:
        recorder.set_csv_paths(str(results_path / "sim_trace"))
        recorder.sim_until = stop_time
        sim.env.process(recorder.snapshot_generator(sim))
        total_frames = stop_time // recorder.snapshot_interval
        print(f"\nGrabacion activada: ~{total_frames} frames "
              f"(intervalo={recorder.snapshot_interval})")

    # ── Ejecucion ─────────────────────────────────────────────────────────
    print(f"\nTiempo de simulacion: {stop_time:,} ut  (≈ {stop_time/1000:.0f} s reales)")
    print("-" * 70)
    sim.run(stop_time)

    # ── Scheduling report (after run, so all decisions are recorded) ───────
    print("\n" + "─" * 70)
    print("INFORME DE SCHEDULING K8s")
    print("─" * 70)
    print(k8s_scheduler.get_scheduling_report())
    print("─" * 70)

    if recorder is not None:
        recorder.capture_frame(stop_time, sim)
        print(f"   📷 Frame final capturado  [t={stop_time}]")

    print("\n" + "=" * 70)
    print("SIMULACION COMPLETADA")
    print("=" * 70 + "\n")

    return sim, results_path
