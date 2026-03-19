"""
Diagrama de despliegue — Sistema de Parqueaderos.

Muestra las tres capas del sistema (Cámara / RPi4 / Cloud) con los dos
flujos de datos diferenciados:

  Flujo A (Inteligencia - azul) : Cámara → YOLOv8_RPi4 → CloudRegistry.
  Flujo B (Seguridad   - rojo)  : Cámara → Passthrough  → CloudVideoStorage.
"""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def create_deployment_diagram(nodes_info, save_path: str):
    """
    Genera y guarda el diagrama de despliegue en ``save_path``.

    Parameters
    ----------
    nodes_info : dict {node_id: {...}} con atributos de cada nodo.
    save_path  : ruta de salida del PNG.
    """
    fig, ax = plt.subplots(figsize=(14, 11))

    y_camera = 0.15
    y_fog    = 0.50
    y_cloud  = 0.82

    # ── EDGE layer: 6 Cámaras IP ──────────────────────────────────────────
    camera_x = np.linspace(0.12, 0.88, 6)
    for i, x in enumerate(camera_x):
        zone = i // 2 + 1
        rect = plt.Rectangle((x - 0.04, y_camera - 0.05), 0.08, 0.10,
                              facecolor="#d0f0c0", edgecolor="darkgreen", linewidth=2)
        ax.add_patch(rect)
        ax.text(x, y_camera + 0.005, f"Cam\nZ{zone}/{i % 2}",
                ha="center", va="center", fontsize=8, fontweight="bold")

    ax.text(0.05, y_camera, "EDGE\nCámaras\nIP 720p",
            ha="center", va="center", fontsize=10, fontweight="bold",
            bbox=dict(boxstyle="round", facecolor="#d0f0c0", alpha=0.8))

    # ── FOG layer: 3 Raspberry Pi 4 ───────────────────────────────────────
    fog_x = [0.25, 0.50, 0.75]
    for i, x in enumerate(fog_x):
        rect = plt.Rectangle((x - 0.09, y_fog - 0.08), 0.18, 0.16,
                              facecolor="#ffe0a0", edgecolor="darkorange", linewidth=3)
        ax.add_patch(rect)
        ax.text(x, y_fog + 0.01, f"RPi4\nZona {i + 1}",
                ha="center", va="center", fontsize=9, fontweight="bold")
        ax.text(x, y_fog - 0.03, "YOLOv8 + Pass.",
                ha="center", va="center", fontsize=7, color="#664400")

    ax.text(0.05, y_fog, "FOG\nRaspberry\nPi 4",
            ha="center", va="center", fontsize=10, fontweight="bold",
            bbox=dict(boxstyle="round", facecolor="#ffe0a0", alpha=0.8))

    # ── CLOUD layer: 2 Servidores ─────────────────────────────────────────
    cloud_x = [0.33, 0.67]
    cloud_labels = ["Cloud\nRegistro\nJSON", "Cloud\nVideo\nStorage"]
    for i, (x, lbl) in enumerate(zip(cloud_x, cloud_labels)):
        rect = plt.Rectangle((x - 0.11, y_cloud - 0.08), 0.22, 0.16,
                              facecolor="#c0004a" if i == 0 else "#7b0000",
                              edgecolor="darkred", linewidth=3)
        ax.add_patch(rect)
        ax.text(x, y_cloud, lbl,
                ha="center", va="center", fontsize=9,
                fontweight="bold", color="white")

    ax.text(0.05, y_cloud, "CLOUD\nServidores",
            ha="center", va="center", fontsize=10, fontweight="bold",
            bbox=dict(boxstyle="round", facecolor="#ffaaaa", alpha=0.8))

    # ── Flechas Flujo A (Inteligencia) — azul ─────────────────────────────
    # Cámara → RPi4 de su zona (frames H.264 para inferencia)
    for i, cam_x in enumerate(camera_x):
        fog_gw = fog_x[i // 2]
        ax.annotate("",
                    xy=(fog_gw, y_fog - 0.08),
                    xytext=(cam_x, y_camera + 0.05),
                    arrowprops=dict(arrowstyle="->", lw=1.5,
                                    color="steelblue", alpha=0.55))

    # RPi4 → CloudRegistry (JSON resultado)
    for x in fog_x:
        ax.annotate("",
                    xy=(cloud_x[0], y_cloud - 0.08),
                    xytext=(x, y_fog + 0.08),
                    arrowprops=dict(arrowstyle="->", lw=2.5,
                                    color="steelblue", alpha=0.75))

    # ── Flechas Flujo B (Seguridad) — rojo ────────────────────────────────
    # Cámara → RPi4 (video crudo — ligeramente desplazado para distinguir)
    for i, cam_x in enumerate(camera_x):
        fog_gw = fog_x[i // 2]
        ax.annotate("",
                    xy=(fog_gw + 0.025, y_fog - 0.08),
                    xytext=(cam_x + 0.015, y_camera + 0.05),
                    arrowprops=dict(arrowstyle="->", lw=1.5,
                                    color="crimson", alpha=0.55,
                                    linestyle="dashed"))

    # RPi4 → CloudVideoStorage (video stream)
    for x in fog_x:
        ax.annotate("",
                    xy=(cloud_x[1], y_cloud - 0.08),
                    xytext=(x + 0.025, y_fog + 0.08),
                    arrowprops=dict(arrowstyle="->", lw=2.5,
                                    color="crimson", alpha=0.75,
                                    linestyle="dashed"))

    # ── Leyenda de flujos ─────────────────────────────────────────────────
    from matplotlib.patches import FancyArrowPatch
    import matplotlib.lines as mlines

    flow_a_line = mlines.Line2D([], [], color="steelblue", linewidth=2.5,
                                label="Flujo A — Inteligencia (YOLOv8 → JSON)")
    flow_b_line = mlines.Line2D([], [], color="crimson", linewidth=2.5,
                                linestyle="dashed",
                                label="Flujo B — Seguridad (Video → Storage)")
    ax.legend(handles=[flow_a_line, flow_b_line],
              loc="upper right", fontsize=9, framealpha=0.9)

    # ── Anotaciones de carga ──────────────────────────────────────────────
    ax.text(0.50, (y_camera + y_fog) / 2 + 0.03,
            "Video H.264\n~20 KB/frame (Flujo A)\n~500 KB/s (Flujo B)",
            ha="center", fontsize=8, color="#333333",
            bbox=dict(boxstyle="round", facecolor="lightyellow", alpha=0.7))

    ax.text(0.50, (y_fog + y_cloud) / 2 + 0.01,
            "JSON ~2 KB (Flujo A) / Video 500 KB (Flujo B)\nInternet ~100 Mbps · PR ~70 ms",
            ha="center", fontsize=8, color="#333333",
            bbox=dict(boxstyle="round", facecolor="#ffe0cc", alpha=0.7))

    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    plt.title(
        "Diagrama de Despliegue — Sistema de Parqueaderos\n"
        "Flujo A (Inteligencia)  ·  Flujo B (Seguridad)",
        fontsize=15, fontweight="bold", pad=18,
    )
    plt.tight_layout()
    plt.savefig(save_path, dpi=300, bbox_inches="tight")
    print(f"   ✓ Diagrama de despliegue guardado en: {save_path}")
    plt.close()
