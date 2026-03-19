"""
Topología jerárquica del sistema de parqueaderos.

Arquitectura
------------
  Cámara IP (edge)  →  Raspberry Pi 4 (fog)  →  Cloud

Nodos
-----
  0 – 5  : Cámaras IP (edge) — 2 por zona × 3 zonas de parqueadero
  6 – 8  : Raspberry Pi 4   (fog) — 1 por zona; ejecutan YOLOv8 + passthrough
  9 – 10 : Servidores Cloud         — registros JSON + almacenamiento de video

Parámetros de red (sim_params/network_params.csv)
--------------------------------------------------
  Cámara → RPi4  : 1 Gbps Ethernet,  PR = 3  ms
  RPi4   → Cloud : 100 Mbps Internet, PR = 70 ms  (enlace compartido flujos A+B)
  Cloud  ↔ Cloud : 10 000 Mbps,       PR = 1  ms  (datacenter)
"""

import random
import networkx as nx
from yafs.topology import Topology


def create_edge_fog_cloud_topology():
    """Crea la topología jerárquica Cámara → RPi4 → Cloud."""
    t = Topology()
    G = nx.DiGraph()

    cameras = {}
    positions = {}

    # ── EDGE LAYER: Cámaras IP ────────────────────────────────────────────
    # Hardware: cámara IP básica; mínimo cómputo (solo captura y transmisión).
    # IPT: ~2 000 MIPS   RAM: 512 MB   BW: 1 Gbps Ethernet   Bitrate: 3.5–5 Mbps
    #
    # Zona 1: Parqueadero Norte  (nodos 0–1)
    for i in range(2):
        node_id = i
        positions[node_id] = (0.2 + random.uniform(-0.07, 0.07),
                               0.80 + random.uniform(-0.06, 0.06))
        cameras[node_id] = {
            "name":  f"Cam_Z1_{i}",
            "zone":  1,
            "type":  "edge",
            "model": "Camara IP 720p",
            "IPT":   2000 * 10**6,
            "RAM":   512,
            "COST":  1,
            "WATT":  5,
        }

    # Zona 2: Parqueadero Central (nodos 2–3)
    for i in range(2):
        node_id = 2 + i
        positions[node_id] = (0.50 + random.uniform(-0.07, 0.07),
                               0.50 + random.uniform(-0.06, 0.06))
        cameras[node_id] = {
            "name":  f"Cam_Z2_{i}",
            "zone":  2,
            "type":  "edge",
            "model": "Camara IP 720p",
            "IPT":   2000 * 10**6,
            "RAM":   512,
            "COST":  1,
            "WATT":  5,
        }

    # Zona 3: Parqueadero Sur   (nodos 4–5)
    for i in range(2):
        node_id = 4 + i
        positions[node_id] = (0.80 + random.uniform(-0.07, 0.07),
                               0.20 + random.uniform(-0.06, 0.06))
        cameras[node_id] = {
            "name":  f"Cam_Z3_{i}",
            "zone":  3,
            "type":  "edge",
            "model": "Camara IP 720p",
            "IPT":   2000 * 10**6,
            "RAM":   512,
            "COST":  1,
            "WATT":  5,
        }

    # ── FOG LAYER: Raspberry Pi 4 ─────────────────────────────────────────
    # CPU   : Quad-core ARM Cortex-A72 @ 1.5 GHz ≈ 6 000 MIPS
    # RAM   : 4 GB (uso efectivo YOLOv8 + buffer video: 600–800 MB)
    # Tareas: inferencia YOLOv8n (Flujo A) + passthrough de video (Flujo B)
    rpi_nodes = {
        6: {"name": "RPi4_Z1", "zone": 1, "type": "fog",
            "model": "Raspberry Pi 4",
            "IPT": 6000 * 10**6, "RAM": 4000, "COST": 2, "WATT": 6},
        7: {"name": "RPi4_Z2", "zone": 2, "type": "fog",
            "model": "Raspberry Pi 4",
            "IPT": 6000 * 10**6, "RAM": 4000, "COST": 2, "WATT": 6},
        8: {"name": "RPi4_Z3", "zone": 3, "type": "fog",
            "model": "Raspberry Pi 4",
            "IPT": 6000 * 10**6, "RAM": 4000, "COST": 2, "WATT": 6},
    }
    positions[6] = (0.20, 0.95)
    positions[7] = (0.50, 0.65)
    positions[8] = (0.80, 0.35)

    # ── CLOUD LAYER: Servidores ───────────────────────────────────────────
    # CPU: ≈ 100 000 MIPS  |  RAM: 64 GB
    # Servidor 9 → lógica de negocio + registro JSON (Flujo A).
    # Servidor 10 → almacenamiento masivo de video (Flujo B).
    cloud_servers = {
        9:  {"name": "Cloud_RegistroJSON", "type": "cloud",
             "model": "Cloud Server",
             "IPT": 100000 * 10**6, "RAM": 64000, "COST": 5, "WATT": 200},
        10: {"name": "Cloud_VideoStorage", "type": "cloud",
             "model": "Cloud Server",
             "IPT": 100000 * 10**6, "RAM": 64000, "COST": 5, "WATT": 200},
    }
    positions[9]  = (0.30, 0.05)
    positions[10] = (0.70, 0.05)

    # ── Agregar nodos ─────────────────────────────────────────────────────
    all_nodes = {**cameras, **rpi_nodes, **cloud_servers}
    for node_id, attrs in all_nodes.items():
        G.add_node(node_id, **attrs)

    # ── ENLACES ───────────────────────────────────────────────────────────
    links = []

    # 1. Cámara → RPi4 de su zona — Gigabit Ethernet
    #    BW = 1 000 Mbps  |  PR = 3 ms
    for node_id, attrs in cameras.items():
        rpi_id = 5 + attrs["zone"]          # zona 1 → 6, zona 2 → 7, zona 3 → 8
        links.append((node_id, rpi_id, 1000, 3))

    # 2. RPi4 ↔ RPi4 — WAN intermedia (opcional, para resiliencia)
    #    BW = 200 Mbps  |  PR = 15 ms
    links.extend([
        (6, 7, 200, 15),
        (7, 8, 200, 15),
        (6, 8, 200, 20),
    ])

    # 3. RPi4 → Cloud — Enlace Internet compartido (Flujos A y B)
    #    BW = 100 Mbps  |  PR = 70 ms (mid de 50–120 ms del CSV)
    for rpi_id in [6, 7, 8]:
        for cloud_id in [9, 10]:
            links.append((rpi_id, cloud_id, 100, 70))

    # 4. Cloud ↔ Cloud — Datacenter (10 Gbps)
    links.append((9, 10, 10000, 1))

    # Todos los enlaces son bidireccionales
    for src, dst, bw, pr in links:
        G.add_edge(src, dst, BW=bw, PR=pr)
        G.add_edge(dst, src, BW=bw, PR=pr)

    t.G = G
    return t, positions, all_nodes
