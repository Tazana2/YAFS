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
    """Crea una topologia por zonas para video, sensores y servicios compartidos.

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
            ram_mb=8192,
            cost=3,
            watt=18,
            cpu=8,
        )

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
            ram_mb=6144,
            cost=3,
            watt=14,
            cpu=8,
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
            ram_mb=16384,
            cost=4,
            watt=28,
            cpu=8,
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
                links.append((edge, gw, 1000, 2))
            for edge in sensor_by_zone[zone]:
                gw = rng.choice(zone_gateways)
                links.append((edge, gw, 200, 2))

            for gw in zone_gateways:
                links.append((gw, f_video, 1000, 2))
                links.append((gw, f_sensor, 200, 1))
        else:
            for edge in video_by_zone[zone]:
                links.append((edge, f_video, 1000, 4))
            for edge in sensor_by_zone[zone]:
                links.append((edge, f_sensor, 200, 3))

    fog_all = fog_video_nodes + fog_sensor_nodes + fog_shared_nodes
    for idx, src in enumerate(fog_all):
        for dst in fog_all[idx + 1:]:
            links.append((src, dst, 300, 10))

    for fnode in fog_all:
        for cnode in cloud_nodes:
            links.append((fnode, cnode, 150, 60))

    for idx, src in enumerate(cloud_nodes):
        for dst in cloud_nodes[idx + 1:]:
            links.append((src, dst, 10000, 2))

    for src, dst, bw, pr in links:
        G.add_edge(src, dst, BW=bw, PR=pr)
        G.add_edge(dst, src, BW=bw, PR=pr)

    t.G = G
    return t, positions, all_nodes
