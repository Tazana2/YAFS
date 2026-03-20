"""Diagrama de despliegue para dos aplicaciones urbanas y servicios compartidos."""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch


def _box(ax, x, y, w, h, label, fc, ec="#2f3b46", txt="#1f2a36", fs=8, r=0.01, lw=1.3):
    rect = FancyBboxPatch(
        (x, y),
        w,
        h,
        boxstyle=f"round,pad=0.004,rounding_size={r}",
        facecolor=fc,
        edgecolor=ec,
        linewidth=lw,
    )
    ax.add_patch(rect)
    ax.text(
        x + w / 2,
        y + h / 2,
        label,
        ha="center",
        va="center",
        fontsize=fs,
        color=txt,
        fontweight="bold",
    )


def _arrow(ax, x0, y0, x1, y1, color, style="-", lw=1.9, rad=0.0):
    ax.annotate(
        "",
        xy=(x1, y1),
        xytext=(x0, y0),
        arrowprops=dict(
            arrowstyle="->",
            lw=lw,
            color=color,
            linestyle=style,
            alpha=0.9,
            shrinkA=2,
            shrinkB=2,
            connectionstyle=f"arc3,rad={rad}",
        ),
    )


def _lane(ax, y, h, label, fc, ec):
    rect = FancyBboxPatch(
        (0.03, y),
        0.94,
        h,
        boxstyle="round,pad=0.006,rounding_size=0.01",
        facecolor=fc,
        edgecolor=ec,
        linewidth=1.3,
        alpha=0.95,
    )
    ax.add_patch(rect)
    ax.text(0.045, y + h - 0.03, label, ha="left", va="center", fontsize=10, fontweight="bold", color="#22303c")


def create_deployment_diagram(nodes_info, save_path: str):
    """Genera un diagrama app-centric de despliegue y flujos principales."""
    _ = nodes_info

    plt.rcParams.update({
        "font.family": "DejaVu Sans",
        "font.size": 9,
        "axes.titlesize": 16,
    })

    fig, ax = plt.subplots(figsize=(15, 9.5), facecolor="#f4f6f8")
    ax.set_facecolor("#f0f3f6")

    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    palette = {
        "edge_layer": "#d8e4ef",
        "fog_layer": "#e8e2d6",
        "cloud_layer": "#e8dcde",
        "edge_video": "#7ea5c4",
        "edge_sensor": "#79afa7",
        "fog_video": "#c1a06a",
        "fog_sensor": "#93b190",
        "fog_shared": "#b3ba9f",
        "cloud_service": "#c58686",
        "platform": "#c8ab78",
        "video_flow": "#2e6c92",
        "sensor_flow": "#3f7c4b",
        "shared_flow": "#8a4545",
        "platform_flow": "#7b6542",
    }

    # Carriles por capa (label en la esquina, no sobre los nodos)
    _lane(ax, 0.07, 0.20, "EDGE LAYER", palette["edge_layer"], "#7a97b1")
    _lane(ax, 0.31, 0.30, "FOG LAYER", palette["fog_layer"], "#9b8764")
    _lane(ax, 0.65, 0.28, "CLOUD LAYER", palette["cloud_layer"], "#9c7676")

    # EDGE
    _box(ax, 0.08, 0.12, 0.14, 0.075, "edge-video\ningestion", palette["edge_video"], txt="#153447")
    _box(ax, 0.08, 0.205, 0.14, 0.075, "edge-sensor\ningestion", palette["edge_sensor"], txt="#163f37")

    # FOG: App 2 (sensor) fila superior
    _box(ax, 0.27, 0.46, 0.14, 0.08, "sensor\npreprocess", palette["fog_sensor"], txt="#1f3b1f")
    _box(ax, 0.44, 0.46, 0.14, 0.08, "sensor-stream\nprocessing", palette["fog_sensor"], txt="#1f3b1f")
    _box(ax, 0.61, 0.46, 0.14, 0.08, "sensor\nprediction", palette["fog_sensor"], txt="#1f3b1f")

    # FOG: App 1 (video) fila inferior
    _box(ax, 0.27, 0.365, 0.14, 0.08, "edge\ninference", palette["fog_video"], txt="#3e2d12")
    _box(ax, 0.44, 0.365, 0.14, 0.08, "tracking\nevent", palette["fog_video"], txt="#3e2d12")
    _box(ax, 0.61, 0.365, 0.14, 0.08, "video-stream\nprocessing", palette["fog_video"], txt="#3e2d12")

    # Integracion auxiliar
    _box(ax, 0.27, 0.315, 0.14, 0.04, "climatology integration", palette["fog_shared"], fs=7.2, txt="#2f3a22")

    # CLOUD services
    _box(ax, 0.10, 0.75, 0.13, 0.09, "storage", palette["cloud_service"], txt="#441c1c")
    _box(ax, 0.27, 0.75, 0.13, 0.09, "api-access", palette["cloud_service"], txt="#441c1c")
    _box(ax, 0.44, 0.75, 0.13, 0.09, "visualization", palette["cloud_service"], txt="#441c1c")
    _box(ax, 0.61, 0.75, 0.13, 0.09, "notification", palette["cloud_service"], txt="#441c1c")
    _box(ax, 0.78, 0.75, 0.13, 0.09, "observability", palette["cloud_service"], txt="#441c1c")

    # Platform lifecycle
    _box(ax, 0.10, 0.88, 0.13, 0.05, "simulation", palette["platform"], txt="#4a3516")
    _box(ax, 0.27, 0.88, 0.13, 0.05, "mlops", palette["platform"], txt="#4a3516")
    _box(ax, 0.44, 0.88, 0.13, 0.05, "deployment", palette["platform"], txt="#4a3516")

    # Flujos App 1 (video) - casi horizontales para legibilidad
    _arrow(ax, 0.22, 0.155, 0.27, 0.405, palette["video_flow"], rad=0.0)
    _arrow(ax, 0.41, 0.405, 0.44, 0.405, palette["video_flow"])
    _arrow(ax, 0.58, 0.405, 0.61, 0.405, palette["video_flow"])
    _arrow(ax, 0.75, 0.405, 0.16, 0.795, palette["video_flow"], rad=0.0)
    _arrow(ax, 0.75, 0.405, 0.67, 0.795, palette["video_flow"], style="--")

    # Flujos App 2 (sensores)
    _arrow(ax, 0.22, 0.242, 0.27, 0.50, palette["sensor_flow"])
    _arrow(ax, 0.41, 0.50, 0.44, 0.50, palette["sensor_flow"])
    _arrow(ax, 0.58, 0.50, 0.61, 0.50, palette["sensor_flow"])
    _arrow(ax, 0.41, 0.335, 0.44, 0.50, "#62733f", style=":", lw=1.5)
    _arrow(ax, 0.75, 0.50, 0.16, 0.795, palette["sensor_flow"], rad=0.0)
    _arrow(ax, 0.75, 0.50, 0.67, 0.795, palette["sensor_flow"], style="--")

    # Cadena de servicios cloud
    _arrow(ax, 0.23, 0.79, 0.27, 0.79, palette["shared_flow"])
    _arrow(ax, 0.40, 0.79, 0.44, 0.79, palette["shared_flow"])
    _arrow(ax, 0.40, 0.79, 0.78, 0.79, palette["shared_flow"], style=":")

    # Platform chain
    _arrow(ax, 0.23, 0.905, 0.27, 0.905, palette["platform_flow"])
    _arrow(ax, 0.40, 0.905, 0.44, 0.905, palette["platform_flow"])
    _arrow(ax, 0.57, 0.905, 0.78, 0.79, palette["platform_flow"])

    # Leyenda textual compacta (no invade el area de nodos)
    ax.text(0.03, 0.965, "Azul: App 1 (video)", fontsize=9, fontweight="bold", color=palette["video_flow"])
    ax.text(0.20, 0.965, "Verde: App 2 (sensores)", fontsize=9, fontweight="bold", color=palette["sensor_flow"])
    ax.text(0.43, 0.965, "Rojo: shared cloud", fontsize=9, fontweight="bold", color=palette["shared_flow"])
    ax.text(0.61, 0.965, "Ocre: platform lifecycle", fontsize=9, fontweight="bold", color=palette["platform_flow"])

    plt.title("Diagrama de Despliegue - Smart City Multiapp", fontsize=16, fontweight="bold", pad=10, color="#1f2a36")
    plt.tight_layout()
    plt.savefig(save_path, dpi=300, bbox_inches="tight")
    print(f"   ✓ Diagrama de despliegue guardado en: {save_path}")
    plt.close()
