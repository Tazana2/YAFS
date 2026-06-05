"""Orquestador de simulacion para aplicaciones urbanas multi-servicio.

La colocacion de modulos de servicio (TYPE_MODULE) se delega al
KubernetesDefaultScheduler, que replica la logica Filter→Score→Bind del
kube-scheduler por defecto.  Las fuentes puras (camaras, sensores) y los
sinks (cloud) se siguen anclando explicitamente al nodo fisico correspondiente
— igual que DaemonSets y managed-services en un cluster Kubernetes real.
"""

import json
import random
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from yafs.core import Sim
from yafs.path_routing import DeviceSpeedAwareRouting, LatencyAwareRouting
from yafs.distribution import exponential_distribution

from fog_simulation.applications import (
    create_platform_lifecycle_app,
    create_sensor_climatology_app,
    create_video_analytics_app,
)
from fog_simulation.simulation.latency_resource_scheduler import (
    LatencyResourceAwareScheduler,
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


def run_simulation(
    topology,
    stop_time: int = 50_000,
    recorder=None,
    scheduler_type: str = "default",
    routing_policy: str = "hop",
    seed: int = 42,
    topology_params: dict | None = None,
    workload_params: dict | None = None,
    scenario_name: str | None = None,
    stress_profile: dict | None = None,
    applied_adjustments: dict | None = None,
    results_dir="results_fog_simulation",
):
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

    scheduler_type = _normalize_scheduler_type(scheduler_type)
    routing_policy = _normalize_routing_policy(routing_policy)
    scheduler_label = _scheduler_label(scheduler_type)
    routing_label = _routing_label(routing_policy)

    _set_global_seed(seed)

    print("INICIANDO SIMULACION — ESCENARIO URBANO MULTIAPP")
    print(f"  Placement: {scheduler_label}")
    print(f"  Routing:   {routing_label}")
    print(f"  Topologia: {topo_label}")
    print("=" * 70)

    results_path = Path(results_dir)
    results_path.mkdir(parents=True, exist_ok=True)

    # ── Aplicaciones ──────────────────────────────────────────────────────
    app_video    = create_video_analytics_app()
    app_sensor   = create_sensor_climatology_app()
    app_platform = create_platform_lifecycle_app()
    workload_profile = _normalize_workload_params(workload_params)
    _scale_app_message_sizes(
        app_video,
        workload_profile["video_message_size_multiplier"],
    )
    _scale_app_message_sizes(
        app_sensor,
        workload_profile["sensor_message_size_multiplier"],
    )

    edge_video, edge_sensor, fog_video, fog_sensor, fog_shared, cloud = (
        _nodes_by_role(topology)
    )

    # ── Scheduler K8s compartido para todo el cluster ─────────────────────
    # Un unico scheduler para las tres apps garantiza que el resource
    # accounting sea global: lo que consume App1 no esta disponible para App2.
    scheduler = _build_scheduler(scheduler_type)

    selector = _build_selector(routing_policy)
    workload_record = {
        "requested": workload_params or {},
        "effective": {
            "video_rate_multiplier": workload_profile["video_rate_multiplier"],
            "sensor_rate_multiplier": workload_profile["sensor_rate_multiplier"],
            "platform_rate_multiplier": workload_profile["platform_rate_multiplier"],
            "video_message_size_multiplier": workload_profile["video_message_size_multiplier"],
            "sensor_message_size_multiplier": workload_profile["sensor_message_size_multiplier"],
            "burst_enabled": workload_profile["burst_enabled"],
            "burst_start": workload_profile["burst_start"],
            "burst_end": workload_profile["burst_end"],
            "burst_multiplier": workload_profile["burst_multiplier"],
        },
        "video_sources": [],
        "sensor_sources": [],
        "climate_source": None,
        "platform_source": None,
    }

    # ── Simulador ─────────────────────────────────────────────────────────
    sim = Sim(topology, default_results_path=str(results_path / "sim_trace"))
    sim.driftguard_scheduler = scheduler
    sim.driftguard_routing_policy = routing_policy

    print(f"\nDesplegando aplicaciones con {scheduler_label}...")
    sim.deploy_app(app_platform, scheduler, selector)
    sim.deploy_app(app_video,    scheduler, selector)
    sim.deploy_app(app_sensor,   scheduler, selector)

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
        dist_seed = _distribution_seed(seed, 1000 + cam_id)
        dist_lambd = _scaled_lambd(
            1200,
            workload_profile["video_rate_multiplier"],
        )
        dist = _build_workload_distribution(
            lambd=dist_lambd,
            seed=dist_seed,
            name=f"VideoSource_{cam_id}",
            workload_profile=workload_profile,
        )
        sim.deploy_source(app_video.name, id_node=cam_id, msg=msg, distribution=dist)
        workload_record["video_sources"].append(
            {
                "node_id": cam_id,
                "message": msg.name,
                "base_lambd": 1200,
                "effective_lambd": dist_lambd,
                "seed": dist_seed,
                "message_bytes": msg.bytes,
            }
        )

    for sensor_id in edge_sensor:
        msg  = app_sensor.get_message("M.Sensor.Batch.Raw")
        dist_seed = _distribution_seed(seed, 2000 + sensor_id)
        dist_lambd = _scaled_lambd(
            1000,
            workload_profile["sensor_rate_multiplier"],
        )
        dist = _build_workload_distribution(
            lambd=dist_lambd,
            seed=dist_seed,
            name=f"SensorSource_{sensor_id}",
            workload_profile=workload_profile,
        )
        sim.deploy_source(app_sensor.name, id_node=sensor_id, msg=msg, distribution=dist)
        workload_record["sensor_sources"].append(
            {
                "node_id": sensor_id,
                "message": msg.name,
                "base_lambd": 1000,
                "effective_lambd": dist_lambd,
                "seed": dist_seed,
                "message_bytes": msg.bytes,
            }
        )

    climate_src_node = fog_shared[0] if fog_shared else fog_sensor[0]
    climate_seed = _distribution_seed(seed, 3001)
    climate_lambd = _scaled_lambd(
        30000,
        workload_profile["sensor_rate_multiplier"],
    )
    sim.deploy_source(
        app_sensor.name,
        id_node=climate_src_node,
        msg=app_sensor.get_message("M.Climate.Sync"),
        distribution=_build_workload_distribution(
            lambd=climate_lambd,
            seed=climate_seed,
            name="ClimateSync",
            workload_profile=workload_profile,
        ),
    )
    workload_record["climate_source"] = {
        "node_id": climate_src_node,
        "message": "M.Climate.Sync",
        "base_lambd": 30000,
        "effective_lambd": climate_lambd,
        "seed": climate_seed,
        "message_bytes": app_sensor.get_message("M.Climate.Sync").bytes,
    }

    platform_seed = _distribution_seed(seed, 4001)
    platform_lambd = _scaled_lambd(
        20000,
        workload_profile["platform_rate_multiplier"],
    )
    sim.deploy_source(
        app_platform.name,
        id_node=cloud["mlops"],
        msg=app_platform.get_message("M.Platform.TrainingBatch"),
        distribution=_build_workload_distribution(
            lambd=platform_lambd,
            seed=platform_seed,
            name="PlatformTraining",
            workload_profile=workload_profile,
        ),
    )
    workload_record["platform_source"] = {
        "node_id": cloud["mlops"],
        "message": "M.Platform.TrainingBatch",
        "base_lambd": 20000,
        "effective_lambd": platform_lambd,
        "seed": platform_seed,
        "message_bytes": app_platform.get_message("M.Platform.TrainingBatch").bytes,
    }

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
    config_path = _write_experiment_config(
        results_path=results_path,
        seed=seed,
        scheduler_type=scheduler_type,
        routing_policy=routing_policy,
        stop_time=stop_time,
        topology_params=topology_params,
        workload_params=workload_record,
        scenario_name=scenario_name,
        stress_profile=stress_profile,
        applied_adjustments=applied_adjustments,
    )

    # ── Scheduling report (after run, so all decisions are recorded) ───────
    print("\n" + "─" * 70)
    print("INFORME DE SCHEDULING")
    print("─" * 70)
    print(scheduler.get_scheduling_report())
    print("─" * 70)

    if hasattr(scheduler, "write_placement_report"):
        placement_path = results_path / "placement_latency_resource.csv"
        written_path = scheduler.write_placement_report(placement_path)
        if written_path is not None:
            print(f"   Placement report: {written_path}")
    print(f"   Experiment config: {config_path}")

    if recorder is not None:
        recorder.capture_frame(stop_time, sim)
        print(f"   📷 Frame final capturado  [t={stop_time}]")

    print("\n" + "=" * 70)
    print("SIMULACION COMPLETADA")
    print("=" * 70 + "\n")

    return sim, results_path


def _normalize_scheduler_type(scheduler_type: str) -> str:
    normalized = str(scheduler_type or "default").strip().lower()
    aliases = {
        "k8s": "default",
        "kubernetes": "default",
        "kubernetes_default": "default",
        "latency-resource": "latency_resource",
        "latencyresource": "latency_resource",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in {"default", "latency_resource"}:
        raise ValueError(
            "scheduler_type must be 'default' or 'latency_resource', "
            f"got {scheduler_type!r}"
        )
    return normalized


def _normalize_routing_policy(routing_policy: str) -> str:
    normalized = str(routing_policy or "hop").strip().lower()
    aliases = {
        "hops": "hop",
        "shortest": "hop",
        "shortest_path": "hop",
        "weighted": "latency",
        "weighted_shortest": "latency",
        "weighted_shortest_path": "latency",
        "latency_aware": "latency",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in {"hop", "latency"}:
        raise ValueError(
            "routing_policy must be 'hop' or 'latency', "
            f"got {routing_policy!r}"
        )
    return normalized


def _scheduler_label(scheduler_type: str) -> str:
    if scheduler_type == "latency_resource":
        return "LatencyResourceAwareScheduler (initial Filter -> Score -> Bind)"
    return "KubernetesDefaultScheduler (Filter -> Score -> Bind)"


def _routing_label(routing_policy: str) -> str:
    if routing_policy == "latency":
        return "LatencyAwareRouting (PR + payload/BW weighted shortest path)"
    return "DeviceSpeedAwareRouting (hop-count shortest path)"


def _build_scheduler(scheduler_type: str):
    if scheduler_type == "latency_resource":
        return LatencyResourceAwareScheduler(
            name="Latency_Resource_Cluster_Scheduler",
            verbose=True,
        )
    return KubernetesDefaultScheduler(
        name="K8s_Cluster_Scheduler",
        verbose=True,
    )


def _build_selector(routing_policy: str):
    if routing_policy == "latency":
        return LatencyAwareRouting()
    return DeviceSpeedAwareRouting()


def _set_global_seed(seed: int | None) -> None:
    if seed is None:
        return
    random.seed(seed)
    try:
        import numpy as np
        np.random.seed(seed)
    except ImportError:
        pass


def _distribution_seed(seed: int | None, offset: int) -> int:
    if seed is None:
        return int(offset)
    return int(seed) * 100000 + int(offset)


def _write_experiment_config(
    results_path: Path,
    seed: int | None,
    scheduler_type: str,
    routing_policy: str,
    stop_time: int,
    topology_params: dict | None,
    workload_params: dict,
    scenario_name: str | None = None,
    stress_profile: dict | None = None,
    applied_adjustments: dict | None = None,
) -> Path:
    config = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "scenario_name": scenario_name,
        "seed": seed,
        "scheduler_type": scheduler_type,
        "routing_policy": routing_policy,
        "stop_time": stop_time,
        "topology_params": topology_params or {},
        "stress_profile": stress_profile or {},
        "workload_params": workload_params,
        "applied_adjustments": applied_adjustments or {},
        "git_commit": _git_commit(),
    }
    output_path = results_path / "experiment_config.json"
    with output_path.open("w", encoding="utf-8") as fh:
        json.dump(config, fh, indent=2, sort_keys=True)
        fh.write("\n")
    return output_path


def _git_commit() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parents[2],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _normalize_workload_params(workload_params: dict | None) -> dict:
    params = dict(workload_params or {})
    return {
        "video_rate_multiplier": _positive_float(
            params.get("video_rate_multiplier", 1.0),
            1.0,
        ),
        "sensor_rate_multiplier": _positive_float(
            params.get("sensor_rate_multiplier", 1.0),
            1.0,
        ),
        "platform_rate_multiplier": _positive_float(
            params.get("platform_rate_multiplier", 1.0),
            1.0,
        ),
        "video_message_size_multiplier": _positive_float(
            params.get("video_message_size_multiplier", 1.0),
            1.0,
        ),
        "sensor_message_size_multiplier": _positive_float(
            params.get("sensor_message_size_multiplier", 1.0),
            1.0,
        ),
        "burst_enabled": bool(params.get("burst_enabled", False)),
        "burst_start": float(params.get("burst_start", 0.0) or 0.0),
        "burst_end": float(params.get("burst_end", 0.0) or 0.0),
        "burst_multiplier": _positive_float(
            params.get("burst_multiplier", 1.0),
            1.0,
        ),
    }


def _positive_float(value, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if parsed <= 0:
        return default
    return parsed


def _scaled_lambd(base_lambd: float, rate_multiplier: float) -> float:
    # Exponential ``lambd`` is the mean inter-arrival time; higher rate means
    # shorter inter-arrival time.
    return float(base_lambd) / max(float(rate_multiplier), 1e-12)


def _build_workload_distribution(
    lambd: float,
    seed: int,
    name: str,
    workload_profile: dict,
):
    if workload_profile.get("burst_enabled"):
        return BurstAwareExponentialDistribution(
            lambd=lambd,
            seed=seed,
            name=name,
            burst_start=workload_profile["burst_start"],
            burst_end=workload_profile["burst_end"],
            burst_multiplier=workload_profile["burst_multiplier"],
        )
    return exponential_distribution(lambd=lambd, seed=seed, name=name)


def _scale_app_message_sizes(app, multiplier: float) -> None:
    if abs(multiplier - 1.0) < 1e-12:
        return
    for message in _iter_unique_messages(app):
        message.bytes = int(round(message.bytes * multiplier))


def _iter_unique_messages(app):
    seen = set()
    for message in getattr(app, "messages", {}).values():
        ident = id(message)
        if ident not in seen:
            seen.add(ident)
            yield message
    for services in getattr(app, "services", {}).values():
        for service in services:
            for key in ("message_in", "message_out"):
                message = service.get(key)
                if message:
                    ident = id(message)
                    if ident not in seen:
                        seen.add(ident)
                        yield message


class BurstAwareExponentialDistribution:
    """Exponential source process with a deterministic burst time window."""

    def __init__(
        self,
        lambd,
        seed,
        name,
        burst_start,
        burst_end,
        burst_multiplier,
    ) -> None:
        self.l = float(lambd)
        self.name = name
        self.rnd = np.random.RandomState(seed)
        self.elapsed = 0.0
        self.burst_start = float(burst_start)
        self.burst_end = float(burst_end)
        self.burst_multiplier = max(float(burst_multiplier), 1e-12)

    def next(self):
        lambd = self.l
        if self.burst_start <= self.elapsed < self.burst_end:
            lambd = self.l / self.burst_multiplier
        value = int(self.rnd.exponential(lambd, size=1)[0])
        if value == 0:
            value = 1
        self.elapsed += value
        return value
