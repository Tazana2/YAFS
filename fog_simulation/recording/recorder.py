"""
SimulationRecorder
==================
Captura frames de la simulación a intervalos regulares y los ensambla en
video al terminar.

Integración con SimPy
---------------------
Añade un proceso generador (``snapshot_generator``) que, cada
``snapshot_interval`` unidades de tiempo simulado:
  1. Hace flush de los CSVs de YAFS.
  2. Lee conteos acumulados de nodos y enlaces.
  3. Dibuja el estado actual de la red y lo guarda como PNG numerado.

Al finalizar, ``make_video()`` ensambla los frames con ffmpeg; si no está
disponible, genera un GIF de respaldo con imageio.

Parámetros
----------
topology           : Topology de YAFS (contiene el grafo G).
positions          : dict {node_id: (x, y)} para el layout del grafo.
nodes_info         : dict {node_id: {...}} con atributos de cada nodo.
results_path       : directorio de salida para frames y video.
snapshot_interval  : unidades de tiempo simulado entre frames (default 1000).
fps                : frames por segundo del video final (default 5).
"""

import csv as csv_module
import subprocess
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.cm as cm
from matplotlib.patches import FancyBboxPatch
from matplotlib.lines import Line2D

import networkx as nx


class SimulationRecorder:
    def __init__(
        self,
        topology,
        positions,
        nodes_info,
        results_path="results_edge_fog_cloud",
        snapshot_interval=1000,
        fps=5,
    ):
        self.topology = topology
        self.positions = positions
        self.nodes_info = nodes_info
        self.results_path = Path(results_path)
        self.snapshot_interval = snapshot_interval
        self.fps = fps
        self.sim_until = 50000  # se actualiza antes de correr

        # Directorio de frames
        self.frames_dir = self.results_path / "frames"
        self.frames_dir.mkdir(parents=True, exist_ok=True)

        # Contadores previos para calcular actividad reciente
        self.prev_node_counts = {n: 0 for n in nodes_info}
        self.prev_link_counts = {e: 0 for e in topology.G.edges()}

        self.frame_count = 0
        self.csv_events_path = None
        self.csv_links_path = None

        # Clasificación de nodos por capa
        self.edge_nodes  = [n for n, a in nodes_info.items() if a["type"] == "edge"]
        self.fog_nodes   = [n for n, a in nodes_info.items() if a["type"] == "fog"]
        self.cloud_nodes = [n for n, a in nodes_info.items() if a["type"] == "cloud"]

        # Layout estable por capas para evitar jitter visual entre frames.
        self.draw_positions = self._build_layered_positions()

    # ------------------------------------------------------------------
    # Configuración
    # ------------------------------------------------------------------

    def set_csv_paths(self, base_path: str):
        """Indica la ruta base de los CSVs generados por YAFS."""
        self.csv_events_path = Path(base_path + ".csv")
        self.csv_links_path  = Path(base_path + "_link.csv")

    # ------------------------------------------------------------------
    # Lectura de métricas
    # ------------------------------------------------------------------

    def _build_layered_positions(self):
        """Ubica nodos en columnas EDGE/FOG/CLOUD para una visualización limpia."""

        def _layer(nodes, x_pos, y_bottom=0.1, y_top=0.9):
            if not nodes:
                return {}
            ordered = sorted(
                nodes,
                key=lambda nid: self.positions.get(nid, (0.0, 0.0))[1],
                reverse=True,
            )
            if len(ordered) == 1:
                return {ordered[0]: (x_pos, (y_bottom + y_top) / 2)}

            step = (y_top - y_bottom) / (len(ordered) - 1)
            return {node: (x_pos, y_top - i * step) for i, node in enumerate(ordered)}

        pos = {}
        pos.update(_layer(self.edge_nodes, 0.18, 0.08, 0.92))
        pos.update(_layer(self.fog_nodes, 0.50, 0.12, 0.88))
        pos.update(_layer(self.cloud_nodes, 0.82, 0.16, 0.84))
        return pos

    def _read_csv_counts(self):
        """Lee los CSVs y devuelve conteos acumulados por nodo y enlace."""
        node_counts = {n: 0 for n in self.nodes_info}
        link_counts = {e: 0 for e in self.topology.G.edges()}

        try:
            if self.csv_events_path and self.csv_events_path.exists():
                with open(self.csv_events_path, "r", newline="") as f:
                    for row in csv_module.DictReader(f):
                        try:
                            dst = int(float(row["TOPO.dst"]))
                            if dst in node_counts:
                                node_counts[dst] += 1
                        except (ValueError, KeyError):
                            pass
        except Exception:
            pass

        try:
            if self.csv_links_path and self.csv_links_path.exists():
                with open(self.csv_links_path, "r", newline="") as f:
                    for row in csv_module.DictReader(f):
                        try:
                            key = (int(float(row["src"])), int(float(row["dst"])))
                            if key in link_counts:
                                link_counts[key] += 1
                        except (ValueError, KeyError):
                            pass
        except Exception:
            pass

        return node_counts, link_counts

    # ------------------------------------------------------------------
    # Captura de frame
    # ------------------------------------------------------------------

    def capture_frame(self, current_time, sim):
        """Genera y guarda un frame PNG con el estado actual."""
        try:
            sim.metrics.flush()
        except Exception:
            pass

        node_counts, link_counts = self._read_csv_counts()

        recent_node = {
            n: max(0, node_counts[n] - self.prev_node_counts.get(n, 0))
            for n in self.nodes_info
        }
        recent_link = {
            e: max(0, link_counts.get(e, 0) - self.prev_link_counts.get(e, 0))
            for e in self.topology.G.edges()
        }

        self.prev_node_counts = dict(node_counts)
        self.prev_link_counts = dict(link_counts)

        self._draw_frame(current_time, node_counts, recent_node, recent_link)
        self.frame_count += 1

    # ------------------------------------------------------------------
    # Dibujado
    # ------------------------------------------------------------------

    def _draw_frame(self, current_time, node_counts, recent_node, recent_link):
        G = self.topology.G

        fig, axes = plt.subplots(
            1, 2, figsize=(20, 9.5),
            gridspec_kw={"width_ratios": [3.6, 1.2]},
            facecolor="#f4f6f8",
        )
        ax = axes[0]
        ax.set_facecolor("#eef2f5")

        palette = {
            "edge_lane": "#dce7ef",
            "fog_lane": "#ece4d7",
            "cloud_lane": "#eaddde",
            "edge_border": "#90a7b6",
            "fog_border": "#ad9468",
            "cloud_border": "#ad8484",
            "edge_link": "#2f6f8f",
            "fog_link": "#8f6b32",
            "cloud_link": "#a54141",
            "dc_link": "#5d5776",
        }

        def lane(x, y, w, h, label, face, edge):
            box = FancyBboxPatch(
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
            ax.add_patch(box)
            ax.text(x + 0.015, y + h - 0.03, label, fontsize=10, fontweight="bold", color="#22303c")

        lane(0.05, 0.04, 0.24, 0.92, "EDGE", palette["edge_lane"], palette["edge_border"])
        lane(0.37, 0.04, 0.26, 0.92, "FOG", palette["fog_lane"], palette["fog_border"])
        lane(0.69, 0.04, 0.24, 0.92, "CLOUD", palette["cloud_lane"], palette["cloud_border"])

        max_node   = max(max(node_counts.values(), default=1), 1)
        max_recent = max(max(recent_node.values(), default=1), 1)
        max_link_r = max(max(recent_link.values(), default=1), 1)

        def node_props(nodelist, base_size, scale_size):
            sizes  = [base_size + scale_size * (node_counts.get(n, 0) / max_node) for n in nodelist]
            colors = [recent_node.get(n, 0) / max_recent for n in nodelist]
            return sizes, colors

        edge_sizes,  edge_c  = node_props(self.edge_nodes,  180,  380)
        fog_sizes,   fog_c   = node_props(self.fog_nodes,   420, 780)
        cloud_sizes, cloud_c = node_props(self.cloud_nodes, 620, 1080)

        def ew(elist, base=0.5, scale=5):
            return [base + scale * (recent_link.get(e, 0) / max_link_r) for e in elist]

        ee = [(u, v) for u, v in G.edges() if u in self.edge_nodes  and v in self.edge_nodes]
        ef = [(u, v) for u, v in G.edges() if (u in self.edge_nodes and v in self.fog_nodes)
                                            or (u in self.fog_nodes  and v in self.edge_nodes)]
        ff = [(u, v) for u, v in G.edges() if u in self.fog_nodes   and v in self.fog_nodes]
        fc = [(u, v) for u, v in G.edges() if (u in self.fog_nodes  and v in self.cloud_nodes)
                                            or (u in self.cloud_nodes and v in self.fog_nodes)]
        cc = [(u, v) for u, v in G.edges() if u in self.cloud_nodes and v in self.cloud_nodes]

        nx.draw_networkx_edges(
            G,
            self.draw_positions,
            edgelist=ee,
            alpha=0.35,
            width=ew(ee, 0.5, 2.0),
            edge_color="#6ea873",
            ax=ax,
            connectionstyle="arc3,rad=0.12",
        )
        nx.draw_networkx_edges(
            G,
            self.draw_positions,
            edgelist=ef,
            alpha=0.8,
            width=ew(ef, 1.2, 3.6),
            edge_color=palette["edge_link"],
            style="dashed",
            ax=ax,
            connectionstyle="arc3,rad=0.06",
        )
        nx.draw_networkx_edges(
            G,
            self.draw_positions,
            edgelist=ff,
            alpha=0.78,
            width=ew(ff, 1.3, 3.9),
            edge_color=palette["fog_link"],
            ax=ax,
            connectionstyle="arc3,rad=0.08",
        )
        nx.draw_networkx_edges(
            G,
            self.draw_positions,
            edgelist=fc,
            alpha=0.82,
            width=ew(fc, 1.5, 4.1),
            edge_color=palette["cloud_link"],
            style="dotted",
            ax=ax,
            connectionstyle="arc3,rad=-0.06",
        )
        nx.draw_networkx_edges(
            G,
            self.draw_positions,
            edgelist=cc,
            alpha=0.8,
            width=ew(cc, 1.7, 4.2),
            edge_color=palette["dc_link"],
            ax=ax,
            connectionstyle="arc3,rad=0.1",
        )

        nx.draw_networkx_nodes(G, self.draw_positions, nodelist=self.edge_nodes,
                               node_color=edge_c, cmap=cm.Blues, vmin=0, vmax=1,
                               node_size=edge_sizes, node_shape="o",
                               edgecolors="#2b5f68", linewidths=1.3, ax=ax)
        nx.draw_networkx_nodes(G, self.draw_positions, nodelist=self.fog_nodes,
                               node_color=fog_c, cmap=cm.YlOrBr, vmin=0, vmax=1,
                               node_size=fog_sizes, node_shape="s",
                               edgecolors="#8f642a", linewidths=2.0, ax=ax)
        nx.draw_networkx_nodes(G, self.draw_positions, nodelist=self.cloud_nodes,
                               node_color=cloud_c, cmap=cm.Reds, vmin=0, vmax=1,
                               node_size=cloud_sizes, node_shape="D",
                               edgecolors="#7f2b2b", linewidths=2.1, ax=ax)

        important = {n: self.nodes_info[n]["name"] for n in self.fog_nodes + self.cloud_nodes}
        edge_lbl  = {n: str(n) for n in self.edge_nodes}
        nx.draw_networkx_labels(G, self.draw_positions, important,
                                font_size=8, font_weight="bold",
                                font_color="#1f2a36", ax=ax)
        nx.draw_networkx_labels(G, self.draw_positions, edge_lbl,
                                font_size=6, font_color="#355d73", ax=ax)

        ax.set_xlim(-0.02, 1.02)
        ax.set_ylim(-0.02, 1.02)
        ax.axis("off")
        ax.set_title(
            f"Simulacion Smart City Edge/Fog/Cloud  |  t = {current_time:,.0f} / {self.sim_until:,.0f}",
            fontsize=13, fontweight="bold", color="#1f2a36", pad=8,
        )

        legend_items = [
            Line2D([0], [0], color="#6ea873", lw=2.5, linestyle="-", label="Edge <-> Edge"),
            Line2D([0], [0], color=palette["edge_link"], lw=2.8, linestyle="--", label="Edge <-> Fog"),
            Line2D([0], [0], color=palette["fog_link"], lw=2.8, linestyle="-", label="Fog <-> Fog"),
            Line2D([0], [0], color=palette["cloud_link"], lw=2.8, linestyle=":", label="Fog <-> Cloud"),
            Line2D([0], [0], color=palette["dc_link"], lw=2.8, linestyle="-", label="Cloud <-> Cloud"),
        ]
        ax.legend(
            handles=legend_items,
            loc="lower center",
            ncol=5,
            fontsize=8,
            framealpha=0.96,
            facecolor="#ffffff",
            edgecolor="#a8b3bc",
        )

        # Barra de progreso
        progress = min(current_time / max(self.sim_until, 1), 1.0)
        bar_ax = fig.add_axes([0.05, 0.02, 0.61, 0.018])
        bar_ax.set_in_layout(False)
        bar_ax.set_facecolor("#dde4ea")
        bar_ax.barh(0, progress, color="#2f6f8f", height=1)
        bar_ax.set_xlim(0, 1)
        bar_ax.set_yticks([])
        bar_ax.set_xticks([0, 0.25, 0.5, 0.75, 1.0])
        bar_ax.set_xticklabels(["0%", "25%", "50%", "75%", "100%"],
                                fontsize=7, color="#253341")
        bar_ax.tick_params(colors="#253341")
        for spine in bar_ax.spines.values():
            spine.set_edgecolor("#a6b3bf")

        # Panel de estadísticas
        ax2 = axes[1]
        ax2.set_facecolor("#f7f9fb")
        ax2.axis("off")

        total_msgs  = sum(node_counts.values())
        total_rec   = sum(recent_node.values())
        edge_total  = sum(node_counts.get(n, 0) for n in self.edge_nodes)
        fog_total   = sum(node_counts.get(n, 0) for n in self.fog_nodes)
        cloud_total = sum(node_counts.get(n, 0) for n in self.cloud_nodes)

        top_node = max(node_counts, key=lambda n: node_counts[n], default=None)
        top_name = self.nodes_info[top_node]["name"] if top_node is not None else "—"
        top_val  = node_counts.get(top_node, 0) if top_node is not None else 0

        stats = (
            "METRICAS DE SIMULACION\n"
            "======================\n\n"
            f" Tiempo simulado  : {current_time:>10,.0f}\n"
            f" Frame            : {self.frame_count + 1:>10}\n"
            f" Progreso         : {100*min(current_time/max(self.sim_until, 1), 1.0):>9.1f}%\n\n"
            "Mensajes acumulados\n"
            f" EDGE             : {edge_total:>10,}\n"
            f" FOG              : {fog_total:>10,}\n"
            f" CLOUD            : {cloud_total:>10,}\n"
            f" TOTAL            : {total_msgs:>10,}\n\n"
            "Actividad reciente\n"
            f" Nuevos mensajes  : {total_rec:>10,}\n\n"
            "Nodo mas activo\n"
            f" {top_name}\n"
            f" {top_val:,} mensajes"
        )
        ax2.text(0.05, 0.97, stats, transform=ax2.transAxes,
                 fontsize=9.2, verticalalignment="top", fontfamily="monospace",
                 color="#253341",
                 bbox=dict(boxstyle="round,pad=0.6", facecolor="#ffffff",
                           edgecolor="#b5c0c9", alpha=0.98))

        fig.suptitle("Edge / Fog / Cloud Smart City Simulation - YAFS",
                     fontsize=15, fontweight="bold", color="#1f2a36", y=0.99)
        fig.patch.set_facecolor("#f4f6f8")
        fig.subplots_adjust(left=0.02, right=0.985, bottom=0.07, top=0.94, wspace=0.06)

        frame_path = self.frames_dir / f"frame_{self.frame_count:05d}.png"
        plt.savefig(str(frame_path), dpi=100, bbox_inches="tight",
                    facecolor=fig.get_facecolor())
        plt.close(fig)

    # ------------------------------------------------------------------
    # Proceso SimPy
    # ------------------------------------------------------------------

    def snapshot_generator(self, sim):
        """Proceso SimPy que captura un frame cada ``snapshot_interval`` unidades."""
        while not sim.stop:
            yield sim.env.timeout(self.snapshot_interval)
            if hasattr(sim, "until") and sim.until:
                self.sim_until = sim.until
            self.capture_frame(sim.env.now, sim)
            print(f"   📷 Frame {self.frame_count:3d} capturado"
                  f"  [t={sim.env.now:,.0f}]", flush=True)

    # ------------------------------------------------------------------
    # Ensamblado del video
    # ------------------------------------------------------------------

    def make_video(self, output_path=None, fps=None):
        """Ensambla los frames PNG en un video usando ffmpeg."""
        if fps is None:
            fps = self.fps
        if output_path is None:
            output_path = self.results_path / "simulation_video.mp4"

        output_path = Path(output_path)
        frames_pattern = str(self.frames_dir / "frame_%05d.png")

        print(f"\n🎬 Ensamblando video con {self.frame_count} frames a {fps} fps...")

        candidates = [
            ("h264_vaapi", ".mp4",  ["-vf", "format=nv12,hwupload", "-qp", "23"]),
            ("h264_nvenc", ".mp4",  ["-cq", "23"]),
            ("h264_qsv",   ".mp4",  ["-global_quality", "23"]),
            ("mpeg4",      ".mp4",  ["-q:v", "3"]),
            ("libvpx_vp9", ".webm", ["-crf", "33", "-b:v", "0"]),
            ("libvpx_vp8", ".webm", ["-crf", "10", "-b:v", "1M"]),
            ("mjpeg",      ".avi",  ["-q:v", "3"]),
        ]

        for codec, ext, extra in candidates:
            candidate_path = output_path.with_suffix(ext)
            if codec == "h264_vaapi":
                cmd = (
                    ["ffmpeg", "-y",
                     "-vaapi_device", "/dev/dri/renderD128",
                     "-framerate", str(fps),
                     "-i", frames_pattern]
                    + extra
                    + ["-c:v", codec, str(candidate_path)]
                )
            else:
                cmd = (
                    ["ffmpeg", "-y",
                     "-framerate", str(fps),
                     "-i", frames_pattern]
                    + extra
                    + ["-c:v", codec,
                       "-pix_fmt", "yuv420p",
                       str(candidate_path)]
                )

            try:
                result = subprocess.run(cmd, capture_output=True, text=True)
                if result.returncode == 0 and candidate_path.exists():
                    size_mb = candidate_path.stat().st_size / 1024 / 1024
                    print(f"   ✓ Video generado con codec '{codec}': {candidate_path}")
                    print(f"   ✓ Tamaño: {size_mb:.1f} MB")
                    return
                else:
                    err = next(
                        (l for l in result.stderr.splitlines()
                         if any(k in l for k in ("Error", "Unknown", "not found"))),
                        "",
                    )
                    print(f"   ↳ '{codec}' no disponible: {err.strip()}")
            except FileNotFoundError:
                print("   ❌ ffmpeg no encontrado en PATH.")
                self._fallback_gif(output_path, fps)
                return

        print("   ⚠️  Ningún codec de video funcionó. Generando GIF...")
        self._fallback_gif(output_path, fps)

    def _fallback_gif(self, output_path: Path, fps: int):
        """Genera un GIF de respaldo con imageio."""
        try:
            import imageio
            frames = sorted(self.frames_dir.glob("frame_*.png"))
            gif_path = str(output_path).replace(".mp4", ".gif")
            with imageio.get_writer(gif_path, mode="I", duration=1.0 / fps) as writer:
                for fp in frames:
                    writer.append_data(imageio.imread(str(fp)))
            print(f"   ✓ GIF generado (respaldo): {gif_path}")
        except ImportError:
            print("   ❌ Instale ffmpeg o imageio para generar el video.")
            print(f"   💡 Frames en: {self.frames_dir}")
            print(f"   💡 Comando manual:")
            print(f"      ffmpeg -framerate {fps} -i "
                  f"'{self.frames_dir}/frame_%05d.png' "
                  f"-c:v libx264 -pix_fmt yuv420p '{output_path}'")
