"""Topologia edge/fog/cloud para dos aplicaciones urbanas y servicios compartidos."""

import random

import networkx as nx

from yafs.topology import Topology


# CPU core counts by tier — used by KubernetesDefaultScheduler for resource accounting.
_TIER_CPU = {
    "edge":  2,    # low-power IoT gateway / IP camera
    "gateway": 1,  # transit-only network hop between edge and fog
    "fog":   16,   # overridden per-role below via cpu parameter
    "cloud": 128,  # cloud service (virtually unbounded)
}


# Link profiles used to emulate realistic heterogeneous backhaul/media.
# BW and PR map directly to YAFS edge attributes.
_LINK_PROFILES = {
    "fiber_access": {"BW": 1000, "PR": 2, "medium": "fiber"},
    "wireless_access": {"BW": 250, "PR": 5, "medium": "wireless"},
    "metro_fiber": {"BW": 800, "PR": 4, "medium": "fiber"},
    "regional_fiber": {"BW": 450, "PR": 12, "medium": "fiber"},
    "microwave_backhaul": {"BW": 180, "PR": 22, "medium": "microwave"},
    "satellite_backhaul": {"BW": 40, "PR": 140, "medium": "satellite"},
    "cloud_backbone": {"BW": 2000, "PR": 3, "medium": "fiber"},
}


def _sample_fog_capacity(rng, role):
    """Sample heterogeneous fog resources within [2-8] CPU cores and [2-16] GB RAM."""
    cpu_options_by_role = {
        "video_processing": [4, 6, 8],
        "sensor_processing": [2, 4, 6],
        "shared_processing": [4, 6, 8],
    }
    ram_options_by_role = {
        "video_processing": [4096, 8192, 12288, 16384],
        "sensor_processing": [2048, 4096, 6144, 8192],
        "shared_processing": [8192, 12288, 16384],
    }

    cpu_cores = rng.choice(cpu_options_by_role.get(role, [2, 4, 6, 8]))
    ram_mb = rng.choice(ram_options_by_role.get(role, [2048, 4096, 8192, 12288, 16384]))
    return cpu_cores, ram_mb


def _estimate_watt(cpu_cores, ram_mb, role, rng):
    """Approximate node power draw from role baseline plus provisioned CPU/RAM."""
    role_base = {
        "video_processing": 8.5,
        "sensor_processing": 6.0,
        "shared_processing": 10.5,
    }
    base_watt = role_base.get(role, 7.0)
    ram_gb = ram_mb / 1024.0
    jitter = rng.uniform(-0.8, 0.8)
    watt = base_watt + (1.4 * cpu_cores) + (0.35 * ram_gb) + jitter
    return max(4, int(round(watt)))


def _mk_node(name, zone, layer, role, model, ipt_mips, ram_mb, cost, watt, cpu=None):
    """
    Build a node attribute dict for YAFS.

    ``cpu`` overrides the default tier value so fog nodes of different roles
    (Edge GPU vs. Fog Node vs. Regional Fog) get distinct core counts.
    """
    cpu_cores = cpu if cpu is not None else _TIER_CPU.get(layer, 4)
    return {
        "name":          name,
        "zone":          zone,
        "type":          layer,
        "role":          role,
        "model":         model,
        "IPT":           ipt_mips * 10**6,
        "RAM":           ram_mb,
        "COST":          cost,
        "WATT":          watt,
        # --- K8s scheduler resource accounting ---
        "CPU":           cpu_cores,
        "CPU_used":      0,
        "RAM_used":      0,
        "unschedulable": False,
    }


def create_edge_fog_cloud_topology(with_gateways: bool = False, gateways_per_zone: int = 1):
    """Crea una topologia por zonas con enlaces heterogeneos y conectividad parcial.

    Parameters
    ----------
    with_gateways : bool, optional
        Si True, inserta nodos gateway de transito entre edge y fog.
    gateways_per_zone : int, optional
        Cantidad de gateways por zona cuando ``with_gateways`` esta activo.
    """
    t = Topology()
    G = nx.DiGraph()

    rng = random.Random(42)
    positions = {}
    all_nodes = {}

    zone_centers = {
        1: (0.18, 0.80),
        2: (0.50, 0.50),
        3: (0.82, 0.20),
    }

    next_id = 0

    # Edge de video: 2 camaras por zona.
    for zone in [1, 2, 3]:
        cx, cy = zone_centers[zone]
        for idx in range(2):
            node_id = next_id
            next_id += 1
            positions[node_id] = (cx + rng.uniform(-0.07, 0.07), cy + rng.uniform(-0.05, 0.05))
            all_nodes[node_id] = _mk_node(
                name=f"Cam_Z{zone}_{idx}",
                zone=zone,
                layer="edge",
                role="video_ingestion",
                model="IP Camera 720p",
                ipt_mips=2000,
                ram_mb=512,
                cost=1,
                watt=5,
                cpu=2,
            )

    # Edge de sensores: 4 nodos por zona.
    for zone in [1, 2, 3]:
        cx, cy = zone_centers[zone]
        for idx in range(4):
            node_id = next_id
            next_id += 1
            positions[node_id] = (cx + rng.uniform(-0.10, 0.10), cy + rng.uniform(-0.10, 0.10))
            all_nodes[node_id] = _mk_node(
                name=f"Sensor_Z{zone}_{idx}",
                zone=zone,
                layer="edge",
                role="sensor_ingestion",
                model="IoT Gateway",
                ipt_mips=1000,
                ram_mb=512,
                cost=1,
                watt=3,
                cpu=2,
            )

    # Fog de video y sensores por zona.
    fog_video_nodes = []
    fog_sensor_nodes = []
    for zone in [1, 2, 3]:
        cx, cy = zone_centers[zone]

        video_cpu, video_ram = _sample_fog_capacity(rng, "video_processing")
        video_watt = _estimate_watt(video_cpu, video_ram, "video_processing", rng)

        node_id = next_id
        next_id += 1
        fog_video_nodes.append(node_id)
        positions[node_id] = (cx, min(0.96, cy + 0.14))
        all_nodes[node_id] = _mk_node(
            name=f"FogVideo_Z{zone}",
            zone=zone,
            layer="fog",
            role="video_processing",
            model="Edge GPU Node",
            ipt_mips=12000,
            ram_mb=video_ram,
            cost=3,
            watt=video_watt,
            cpu=video_cpu,
        )

        sensor_cpu, sensor_ram = _sample_fog_capacity(rng, "sensor_processing")
        sensor_watt = _estimate_watt(sensor_cpu, sensor_ram, "sensor_processing", rng)

        node_id = next_id
        next_id += 1
        fog_sensor_nodes.append(node_id)
        positions[node_id] = (cx + 0.06, min(0.98, cy + 0.06))
        all_nodes[node_id] = _mk_node(
            name=f"FogSensor_Z{zone}",
            zone=zone,
            layer="fog",
            role="sensor_processing",
            model="Fog Node",
            ipt_mips=8000,
            ram_mb=sensor_ram,
            cost=3,
            watt=sensor_watt,
            cpu=sensor_cpu,
        )

    # Gateways de transito opcionales por zona (solo enrutamiento).
    gateway_by_zone = {z: [] for z in [1, 2, 3]}
    if with_gateways:
        gateways_per_zone = max(1, int(gateways_per_zone))
        for zone in [1, 2, 3]:
            cx, cy = zone_centers[zone]
            for idx in range(gateways_per_zone):
                node_id = next_id
                next_id += 1
                x_off = -0.04 + (idx * 0.08 / max(1, gateways_per_zone - 1))
                positions[node_id] = (cx + x_off, min(0.98, cy + 0.09))
                all_nodes[node_id] = _mk_node(
                    name=f"Gateway_Z{zone}_{idx}",
                    zone=zone,
                    layer="gateway",
                    role="network_transit",
                    model="Edge Transit Gateway",
                    ipt_mips=500,
                    ram_mb=256,
                    cost=1,
                    watt=2,
                    cpu=1,
                )
                gateway_by_zone[zone].append(node_id)

    # Fog compartido para agregacion regional.
    fog_shared_nodes = []
    for idx, pos in enumerate([(0.35, 0.70), (0.65, 0.35)], start=1):
        shared_cpu, shared_ram = _sample_fog_capacity(rng, "shared_processing")
        shared_watt = _estimate_watt(shared_cpu, shared_ram, "shared_processing", rng)

        node_id = next_id
        next_id += 1
        fog_shared_nodes.append(node_id)
        positions[node_id] = pos
        all_nodes[node_id] = _mk_node(
            name=f"FogShared_{idx}",
            zone=0,
            layer="fog",
            role="shared_processing",
            model="Regional Fog",
            ipt_mips=15000,
            ram_mb=shared_ram,
            cost=4,
            watt=shared_watt,
            cpu=shared_cpu,
        )

    # Cloud centralizado: un solo nodo para servicios gestionados.
    # RAM dimensionada para alojar MLOps y backends de almacenamiento.
    cloud_nodes = []
    node_id = next_id
    next_id += 1
    cloud_nodes.append(node_id)
    positions[node_id] = (0.56, 0.06)
    all_nodes[node_id] = _mk_node(
        name="Cloud_core",
        zone=0,
        layer="cloud",
        role="cloud_core",
        model="Cloud Service Hub",
        ipt_mips=100000,
        ram_mb=65536,
        cost=5,
        watt=180,
        cpu=16,
    )

    for node_id, attrs in all_nodes.items():
        G.add_node(node_id, **attrs)

    links = []

    def add_link(src, dst, profile_name, link_class):
        links.append((src, dst, profile_name, link_class))

    video_edges = [n for n, a in all_nodes.items() if a["type"] == "edge" and a["role"] == "video_ingestion"]
    sensor_edges = [n for n, a in all_nodes.items() if a["type"] == "edge" and a["role"] == "sensor_ingestion"]

    video_by_zone = {z: [n for n in video_edges if all_nodes[n]["zone"] == z] for z in [1, 2, 3]}
    sensor_by_zone = {z: [n for n in sensor_edges if all_nodes[n]["zone"] == z] for z in [1, 2, 3]}
    fog_video_by_zone = {all_nodes[n]["zone"]: n for n in fog_video_nodes}
    fog_sensor_by_zone = {all_nodes[n]["zone"]: n for n in fog_sensor_nodes}

    for zone in [1, 2, 3]:
        f_video = fog_video_by_zone[zone]
        f_sensor = fog_sensor_by_zone[zone]

        zone_gateways = gateway_by_zone.get(zone, [])
        if with_gateways and zone_gateways:
            for edge in video_by_zone[zone]:
                gw = rng.choice(zone_gateways)
                add_link(edge, gw, "fiber_access", "edge_access")
            for edge in sensor_by_zone[zone]:
                gw = rng.choice(zone_gateways)
                add_link(edge, gw, "wireless_access", "edge_access")

            for gw in zone_gateways:
                add_link(gw, f_video, "fiber_access", "gateway_uplink")
                add_link(gw, f_sensor, "wireless_access", "gateway_uplink")
        else:
            for edge in video_by_zone[zone]:
                add_link(edge, f_video, "fiber_access", "edge_uplink")
            for edge in sensor_by_zone[zone]:
                add_link(edge, f_sensor, "wireless_access", "edge_uplink")

    # Fog fabric (phase 1 realism): sparse and geography-aware.
    # 1) Intra-zone: local video/sensor fog pair.
    for zone in [1, 2, 3]:
        add_link(
            fog_video_by_zone[zone],
            fog_sensor_by_zone[zone],
            "metro_fiber",
            "intra_zone_fog",
        )

    # 2) Zone-to-regional aggregation: no full mesh.
    shared_west = fog_shared_nodes[0] if len(fog_shared_nodes) >= 1 else None
    shared_east = fog_shared_nodes[1] if len(fog_shared_nodes) >= 2 else shared_west

    zone_to_shared = {
        1: [shared_west],
        2: [shared_west, shared_east],  # central zone has dual-homing.
        3: [shared_east],
    }

    for zone in [1, 2, 3]:
        shared_targets = [sid for sid in zone_to_shared[zone] if sid is not None]
        if not shared_targets:
            continue

        add_link(
            fog_video_by_zone[zone],
            shared_targets[0],
            "regional_fiber",
            "fog_uplink_primary",
        )
        add_link(
            fog_sensor_by_zone[zone],
            shared_targets[0],
            "regional_fiber",
            "fog_uplink_primary",
        )

        # Optional backup in the central zone through a different medium.
        if len(shared_targets) > 1:
            add_link(
                fog_video_by_zone[zone],
                shared_targets[1],
                "microwave_backhaul",
                "fog_uplink_backup",
            )

    # 3) Inter-regional shared fog link.
    if len(fog_shared_nodes) > 1:
        add_link(
            fog_shared_nodes[0],
            fog_shared_nodes[1],
            "microwave_backhaul",
            "inter_region_fog",
        )

    # 4) Cloud uplinks: shared fogs have strong fiber uplinks.
    for fnode in fog_shared_nodes:
        for cnode in cloud_nodes:
            add_link(fnode, cnode, "regional_fiber", "cloud_uplink_primary")

    # 5) Selected direct uplinks for heterogeneity and regional asymmetry.
    if cloud_nodes:
        cloud_core = cloud_nodes[0]
        add_link(
            fog_video_by_zone[2],
            cloud_core,
            "wireless_access",
            "cloud_uplink_backup",
        )
        add_link(
            fog_sensor_by_zone[3],
            cloud_core,
            "satellite_backhaul",
            "cloud_uplink_remote",
        )

    for idx, src in enumerate(cloud_nodes):
        for dst in cloud_nodes[idx + 1:]:
            add_link(src, dst, "cloud_backbone", "cloud_core")

    for src, dst, profile_name, link_class in links:
        profile = _LINK_PROFILES[profile_name]
        attrs = {
            "BW": profile["BW"],
            "PR": profile["PR"],
            "LINK_PROFILE": profile_name,
            "LINK_MEDIUM": profile["medium"],
            "LINK_CLASS": link_class,
        }
        G.add_edge(src, dst, **attrs)
        G.add_edge(dst, src, **attrs)

    t.G = G
    return t, positions, all_nodes
