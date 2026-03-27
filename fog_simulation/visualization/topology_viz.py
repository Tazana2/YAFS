"""
Visualizacion estatica de topologia para el escenario smart city.

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
from matplotlib.patches import FancyBboxPatch
from matplotlib.lines import Line2D
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

    camera_nodes  = [n for n, a in nodes_info.items() if a["type"] == "edge"]
    gateway_nodes = [n for n, a in nodes_info.items() if a["type"] == "gateway"]
    fog_nodes     = [n for n, a in nodes_info.items() if a["type"] == "fog"]
    cloud_nodes   = [n for n, a in nodes_info.items() if a["type"] == "cloud"]

    plt.rcParams.update({
        "font.family": "DejaVu Sans",
        "font.size": 10,
        "axes.titlesize": 17,
        "axes.titleweight": "semibold",
    })

    fig, ax = plt.subplots(figsize=(16, 12), facecolor="#f4f6f8")
    ax.set_facecolor("#eef2f5")

    colors = {
        "edge_node": "#5a9aa8",
        "edge_border": "#2b5f68",
        "fog_node": "#d2a15a",
        "fog_border": "#8e642a",
        "cloud_node": "#c76262",
        "cloud_border": "#7f2b2b",
        "edge_link": "#2f6f8f",
        "gateway_link": "#3f7b5b",
        "gateway_node": "#7fb08a",
        "gateway_border": "#2f6b3d",
        "fog_link": "#8f6b32",
        "cloud_link": "#a54141",
        "dc_link": "#5d5776",
    }

    # Reubica nodos en columnas por capa para evitar cruces excesivos.
    def layered_positions(nodes, x_pos, y_bottom=0.12, y_top=0.88):
        if not nodes:
            return {}
        nodes_sorted = sorted(nodes, key=lambda nid: positions.get(nid, (0.0, 0.0))[1], reverse=True)
        if len(nodes_sorted) == 1:
            return {nodes_sorted[0]: (x_pos, (y_bottom + y_top) / 2)}
        ys = [y_top - i * ((y_top - y_bottom) / (len(nodes_sorted) - 1)) for i in range(len(nodes_sorted))]
        return {node: (x_pos, yv) for node, yv in zip(nodes_sorted, ys)}

    draw_pos = {}
    has_gateway = len(gateway_nodes) > 0
    if has_gateway:
        draw_pos.update(layered_positions(camera_nodes, 0.12, 0.10, 0.90))
        draw_pos.update(layered_positions(gateway_nodes, 0.36, 0.12, 0.88))
        draw_pos.update(layered_positions(fog_nodes, 0.60, 0.12, 0.88))
        draw_pos.update(layered_positions(cloud_nodes, 0.84, 0.18, 0.82))
    else:
        draw_pos.update(layered_positions(camera_nodes, 0.18, 0.10, 0.90))
        draw_pos.update(layered_positions(fog_nodes, 0.50, 0.12, 0.88))
        draw_pos.update(layered_positions(cloud_nodes, 0.82, 0.18, 0.82))

    def draw_lane(x, y, w, h, label, face, edge):
        lane = FancyBboxPatch(
            (x, y),
            w,
            h,
            boxstyle="round,pad=0.006,rounding_size=0.01",
            facecolor=face,
            edgecolor=edge,
            linewidth=1.2,
            alpha=0.9,
            zorder=0,
        )
        ax.add_patch(lane)
        ax.text(x + 0.015, y + h - 0.03, label, fontsize=10, fontweight="bold", color="#263341")

    if has_gateway:
        draw_lane(0.02, 0.05, 0.20, 0.90, "EDGE", "#dde8ee", "#8aa0af")
        draw_lane(0.26, 0.05, 0.20, 0.90, "GATEWAY", "#e1ecdf", "#87a487")
        draw_lane(0.50, 0.05, 0.20, 0.90, "FOG", "#ece4d6", "#ad9468")
        draw_lane(0.74, 0.05, 0.20, 0.90, "CLOUD", "#ebdddf", "#aa7f7f")
    else:
        draw_lane(0.05, 0.05, 0.24, 0.90, "EDGE", "#dde8ee", "#8aa0af")
        draw_lane(0.37, 0.05, 0.26, 0.90, "FOG", "#ece4d6", "#ad9468")
        draw_lane(0.69, 0.05, 0.24, 0.90, "CLOUD", "#ebdddf", "#aa7f7f")

    # ── Filtro de listas de aristas ────────────────────────────────────────
    def edges_of(src_set, dst_set):
        return [(u, v) for u, v in G.edges()
                if u in src_set and v in dst_set]

    # Edge → Gateway o Edge → Fog (si no hay gateway)
    edge_upstream = gateway_nodes if has_gateway else fog_nodes
    nx.draw_networkx_edges(G, draw_pos,
                        edgelist=edges_of(camera_nodes, edge_upstream)
                                + edges_of(edge_upstream, camera_nodes),
            alpha=0.75, width=2.4, edge_color=colors["edge_link"],
                style="dashed", connectionstyle="arc3,rad=0.05")
    # Gateway ↔ Fog (solo si existe capa gateway)
    if has_gateway:
        nx.draw_networkx_edges(G, draw_pos,
                            edgelist=edges_of(gateway_nodes, fog_nodes)
                                    + edges_of(fog_nodes, gateway_nodes),
                alpha=0.78, width=2.6, edge_color=colors["gateway_link"],
                    style="-", connectionstyle="arc3,rad=0.06")
    # RPi4 ↔ RPi4 (WAN)
    nx.draw_networkx_edges(G, draw_pos,
                        edgelist=edges_of(fog_nodes, fog_nodes),
        alpha=0.78, width=2.6, edge_color=colors["fog_link"], connectionstyle="arc3,rad=0.08")
    # RPi4 → Cloud (Flujos A y B)
    nx.draw_networkx_edges(G, draw_pos,
                        edgelist=edges_of(fog_nodes, cloud_nodes)
                                + edges_of(cloud_nodes, fog_nodes),
            alpha=0.8, width=3.0, edge_color=colors["cloud_link"],
                style="dotted", connectionstyle="arc3,rad=-0.05")
    # Cloud ↔ Cloud (datacenter)
    nx.draw_networkx_edges(G, draw_pos,
                        edgelist=edges_of(cloud_nodes, cloud_nodes),
        alpha=0.8, width=3.0, edge_color=colors["dc_link"], connectionstyle="arc3,rad=0.1")

    # ── Nodos ─────────────────────────────────────────────────────────────
    nx.draw_networkx_nodes(G, draw_pos, nodelist=camera_nodes,
                            node_color=colors["edge_node"], node_size=430,
                            node_shape="o", edgecolors=colors["edge_border"], linewidths=2,
                            label="Edge (Cámara IP 720p)")
    if has_gateway:
        nx.draw_networkx_nodes(G, draw_pos, nodelist=gateway_nodes,
                                node_color=colors["gateway_node"], node_size=620,
                                node_shape="h", edgecolors=colors["gateway_border"], linewidths=2.2,
                                label="Gateway (tránsito de red)")
    nx.draw_networkx_nodes(G, draw_pos, nodelist=fog_nodes,
                            node_color=colors["fog_node"], node_size=920,
                            node_shape="s", edgecolors=colors["fog_border"], linewidths=2.6,
                            label="Fog (Raspberry Pi 4 — YOLOv8)")
    nx.draw_networkx_nodes(G, draw_pos, nodelist=cloud_nodes,
                            node_color=colors["cloud_node"], node_size=1350,
                            node_shape="D", edgecolors=colors["cloud_border"], linewidths=2.6,
                            label="Cloud (Registro JSON / Video Storage)")

    # ── Etiquetas ─────────────────────────────────────────────────────────
    nx.draw_networkx_labels(G, draw_pos,
                            {n: nodes_info[n]["name"] for n in gateway_nodes + fog_nodes + cloud_nodes},
                            font_size=8, font_weight="bold", font_color="#1f2a36")
    nx.draw_networkx_labels(G, draw_pos,
                            {n: nodes_info[n]["name"] for n in camera_nodes},
                            font_size=7, font_color="#2b5f68")

    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    n_edge = len(camera_nodes)
    n_gateway = len(gateway_nodes)
    n_fog = len(fog_nodes)
    n_cloud = len(cloud_nodes)
    if has_gateway:
        title = (
            "Topología Smart City - Vista Jerárquica Edge/Gateway/Fog/Cloud\n"
            f"{n_edge} Edge  +  {n_gateway} Gateway  +  {n_fog} Fog  +  {n_cloud} Cloud"
        )
    else:
        title = (
            "Topología Smart City - Vista Jerárquica Edge/Fog/Cloud\n"
            f"{n_edge} Edge  +  {n_fog} Fog  +  {n_cloud} Cloud"
        )
    plt.title(
        title,
        pad=12,
    )

    legend_items = [
        Line2D([0], [0], color=colors["edge_link"], lw=2.2, linestyle="--",
               label="Edge -> Gateway" if has_gateway else "Edge -> Fog"),
        Line2D([0], [0], color=colors["fog_link"], lw=2.8, linestyle="-", label="Fog <-> Fog"),
        Line2D([0], [0], color=colors["cloud_link"], lw=3, linestyle=":", label="Fog -> Cloud"),
        Line2D([0], [0], color=colors["dc_link"], lw=3.2, linestyle="-", label="Cloud <-> Cloud"),
    ]
    if has_gateway:
        legend_items.insert(1, Line2D([0], [0], color=colors["gateway_link"], lw=2.6,
                                      linestyle="-", label="Gateway <-> Fog"))
    node_handles, node_labels = ax.get_legend_handles_labels()
    plt.legend(handles=node_handles + legend_items, loc="lower center", ncol=4, fontsize=9,
                framealpha=0.95, facecolor="#ffffff", edgecolor="#a7b2bc")
    plt.tight_layout()

    if save_path:
        plt.savefig(save_path, dpi=300, bbox_inches="tight")
        print(f"   ✓ Topología guardada en: {save_path}")
    plt.close()
