"""
Visualización estática de la topología del sistema de parqueaderos.

Capas
-----
  EDGE  : Cámaras IP (círculos verdes).
  FOG   : Raspberry Pi 4 (cuadrados naranjas).
  CLOUD : Servidores cloud (diamantes rojos).

Flujos representados
--------------------
  Azul punteado  — Cámara → RPi4 (video crudo, Flujos A y B).
  Naranja        — RPi4 ↔ RPi4 (WAN de respaldo).
  Rojo punteado  — RPi4 → Cloud (JSON + video almacenado).
  Morado         — Cloud ↔ Cloud (datacenter).
"""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
import networkx as nx


def visualize_topology(topology, positions, nodes_info, save_path=None):
    """
    Dibuja la topología del parqueadero y, opcionalmente, la guarda en disco.

    Parameters
    ----------
    topology   : Topology de YAFS.
    positions  : dict {node_id: (x, y)}.
    nodes_info : dict {node_id: {...}} con atributos.
    save_path  : ruta de salida del PNG (None = no guarda).
    """
    G = topology.G

    camera_nodes = [n for n, a in nodes_info.items() if a["type"] == "edge"]
    fog_nodes    = [n for n, a in nodes_info.items() if a["type"] == "fog"]
    cloud_nodes  = [n for n, a in nodes_info.items() if a["type"] == "cloud"]

    fig, ax = plt.subplots(figsize=(16, 12))

    # ── Filtro de listas de aristas ────────────────────────────────────────
    def edges_of(src_set, dst_set):
        return [(u, v) for u, v in G.edges()
                if u in src_set and v in dst_set]

    # Cámara → RPi4 (Flujos A y B)
    nx.draw_networkx_edges(G, positions,
                           edgelist=edges_of(camera_nodes, fog_nodes)
                                  + edges_of(fog_nodes, camera_nodes),
                           alpha=0.45, width=2, edge_color="steelblue",
                           style="dashed")
    # RPi4 ↔ RPi4 (WAN)
    nx.draw_networkx_edges(G, positions,
                           edgelist=edges_of(fog_nodes, fog_nodes),
                           alpha=0.5, width=3, edge_color="orange")
    # RPi4 → Cloud (Flujos A y B)
    nx.draw_networkx_edges(G, positions,
                           edgelist=edges_of(fog_nodes, cloud_nodes)
                                  + edges_of(cloud_nodes, fog_nodes),
                           alpha=0.65, width=3, edge_color="crimson",
                           style="dotted")
    # Cloud ↔ Cloud (datacenter)
    nx.draw_networkx_edges(G, positions,
                           edgelist=edges_of(cloud_nodes, cloud_nodes),
                           alpha=0.75, width=4, edge_color="mediumpurple")

    # ── Nodos ─────────────────────────────────────────────────────────────
    nx.draw_networkx_nodes(G, positions, nodelist=camera_nodes,
                           node_color="lightgreen", node_size=400,
                           node_shape="o", edgecolors="darkgreen", linewidths=2,
                           label="Edge (Cámara IP 720p)")
    nx.draw_networkx_nodes(G, positions, nodelist=fog_nodes,
                           node_color="orange", node_size=900,
                           node_shape="s", edgecolors="darkorange", linewidths=3,
                           label="Fog (Raspberry Pi 4 — YOLOv8)")
    nx.draw_networkx_nodes(G, positions, nodelist=cloud_nodes,
                           node_color="crimson", node_size=1300,
                           node_shape="D", edgecolors="darkred", linewidths=3,
                           label="Cloud (Registro JSON / Video Storage)")

    # ── Etiquetas ─────────────────────────────────────────────────────────
    nx.draw_networkx_labels(G, positions,
                            {n: nodes_info[n]["name"] for n in fog_nodes + cloud_nodes},
                            font_size=8, font_weight="bold")
    nx.draw_networkx_labels(G, positions,
                            {n: nodes_info[n]["name"] for n in camera_nodes},
                            font_size=7, font_color="darkgreen")

    # ── Zonas de parqueadero ───────────────────────────────────────────────
    zona_cfg = [
        (Rectangle((0.05, 0.68), 0.25, 0.25, alpha=0.2),
         "lightblue",  (0.175, 0.92), "Zona 1: Parqueadero Norte"),
        (Rectangle((0.35, 0.38), 0.25, 0.25, alpha=0.2),
         "lightyellow", (0.475, 0.62), "Zona 2: Parqueadero Central"),
        (Rectangle((0.65, 0.08), 0.25, 0.25, alpha=0.2),
         "lightcoral",  (0.775, 0.32), "Zona 3: Parqueadero Sur"),
    ]
    for rect, color, (tx, ty), name in zona_cfg:
        rect.set_facecolor(color)
        rect.set_edgecolor("gray")
        rect.set_linewidth(2)
        ax.add_patch(rect)
        ax.text(tx, ty, name, ha="center", fontsize=10, fontweight="bold",
                bbox=dict(boxstyle="round", facecolor=color, alpha=0.7))

    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    plt.title(
        "Arquitectura — Sistema de Parqueaderos con Visión Artificial\n"
        "6 Cámaras IP  +  3 Raspberry Pi 4 (YOLOv8)  +  2 Servidores Cloud",
        fontsize=16, fontweight="bold", pad=20,
    )
    plt.legend(loc="upper left", fontsize=10, framealpha=0.9)
    plt.tight_layout()

    if save_path:
        plt.savefig(save_path, dpi=300, bbox_inches="tight")
        print(f"   ✓ Topología guardada en: {save_path}")
    plt.close()
