"""Analisis de resultados para escenario urbano multiaplicacion."""

from pathlib import Path
import re

from yafs.application import Application

from fog_simulation.applications import (
    create_platform_lifecycle_app,
    create_sensor_climatology_app,
    create_video_analytics_app,
)


def _module_resource_requirements() -> dict[tuple[str, str], tuple[float, float]]:
    """Construye un mapa (app, module) -> (CPU_req, RAM_req_MB)."""
    requirements = {}

    for factory in (
        create_video_analytics_app,
        create_sensor_climatology_app,
        create_platform_lifecycle_app,
    ):
        app = factory()
        for module_entry in app.data:
            module_name = list(module_entry.keys())[0]
            attrs = list(module_entry.values())[0]

            if attrs.get("Type") != Application.TYPE_MODULE:
                continue

            cpu_req = float(attrs.get("CPU_req", 0) or 0)
            ram_req = float(attrs.get("RAM_req", attrs.get("RAM", 0)) or 0)
            requirements[(app.name, module_name)] = (cpu_req, ram_req)

    return requirements


def _build_usage_timeseries(df_messages, nodes_info: dict):
    """
    Reconstruye uso activo de CPU/RAM por nodo desde ventanas [time_in, time_out].

    Cada evento COMP_M aporta CPU_req/RAM_req del modulo mientras esta en ejecucion.
    """
    requirements = _module_resource_requirements()
    node_events = {int(node_id): [] for node_id in nodes_info.keys()}

    comp_df = df_messages
    if "type" in comp_df.columns:
        comp_df = comp_df[comp_df["type"] == "COMP_M"]

    required_cols = ["app", "module", "TOPO.dst", "time_in", "time_out"]
    if any(col not in comp_df.columns for col in required_cols):
        return {}, []

    sim_end = 0.0

    for app_name, module_name, topo_dst, time_in, time_out in comp_df[required_cols].itertuples(index=False, name=None):
        try:
            node_id = int(float(topo_dst))
            start_t = float(time_in)
            end_t = float(time_out)
        except (TypeError, ValueError):
            continue

        if end_t < start_t:
            start_t, end_t = end_t, start_t

        sim_end = max(sim_end, end_t)

        cpu_req, ram_req = requirements.get((str(app_name), str(module_name)), (0.0, 0.0))
        if node_id not in node_events or (cpu_req <= 0 and ram_req <= 0):
            continue

        node_events[node_id].append((start_t, cpu_req, ram_req))
        node_events[node_id].append((end_t, -cpu_req, -ram_req))

    node_series = {}
    csv_rows = []

    for node_id in sorted(nodes_info.keys()):
        events = sorted(node_events.get(node_id, []), key=lambda e: e[0])
        deltas_by_time = {}

        for event_t, delta_cpu, delta_ram in events:
            if event_t not in deltas_by_time:
                deltas_by_time[event_t] = [0.0, 0.0]
            deltas_by_time[event_t][0] += delta_cpu
            deltas_by_time[event_t][1] += delta_ram

        time_axis = [0.0]
        cpu_axis = [0.0]
        ram_axis = [0.0]
        cpu_active = 0.0
        ram_active = 0.0

        for event_t in sorted(deltas_by_time.keys()):
            if event_t > time_axis[-1]:
                time_axis.append(event_t)
                cpu_axis.append(cpu_active)
                ram_axis.append(ram_active)

            cpu_active = max(0.0, cpu_active + deltas_by_time[event_t][0])
            ram_active = max(0.0, ram_active + deltas_by_time[event_t][1])

            time_axis.append(event_t)
            cpu_axis.append(cpu_active)
            ram_axis.append(ram_active)

        if time_axis[-1] < sim_end:
            time_axis.append(sim_end)
            cpu_axis.append(cpu_active)
            ram_axis.append(ram_active)

        node_series[node_id] = {
            "time": time_axis,
            "cpu": cpu_axis,
            "ram": ram_axis,
        }

        node = nodes_info[node_id]
        cpu_cap = float(node.get("CPU", 0) or 0)
        ram_cap = float(node.get("RAM", 0) or 0)
        node_name = node.get("name", f"Nodo {node_id}")
        node_type = node.get("type", "unknown")

        for idx, event_t in enumerate(time_axis):
            cpu_used = cpu_axis[idx]
            ram_used = ram_axis[idx]

            csv_rows.append(
                {
                    "time": event_t,
                    "node_id": node_id,
                    "node_name": node_name,
                    "node_type": node_type,
                    "cpu_used": cpu_used,
                    "cpu_capacity": cpu_cap,
                    "cpu_pct": (cpu_used / cpu_cap * 100.0) if cpu_cap > 0 else 0.0,
                    "ram_used_mb": ram_used,
                    "ram_capacity_mb": ram_cap,
                    "ram_pct": (ram_used / ram_cap * 100.0) if ram_cap > 0 else 0.0,
                }
            )

    return node_series, csv_rows


def _slugify(value: str) -> str:
    """Genera nombres de archivo seguros para cada nodo."""
    slug = re.sub(r"[^A-Za-z0-9_-]+", "_", value).strip("_").lower()
    return slug or "nodo"


def _export_node_resource_charts(results_path: Path, nodes_info: dict, node_series: dict):
    """Guarda graficas separadas de CPU y RAM por nodo."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("⚠️  matplotlib no disponible. Se omiten gráficas de CPU/RAM por nodo.")
        return None, 0, None, 0

    cpu_output_dir = results_path / "cpu_usage"
    ram_output_dir = results_path / "ram_usage"
    cpu_output_dir.mkdir(parents=True, exist_ok=True)
    ram_output_dir.mkdir(parents=True, exist_ok=True)
    cpu_generated = 0
    ram_generated = 0

    for node_id in sorted(nodes_info.keys()):
        node = nodes_info[node_id]
        series = node_series.get(node_id, {"time": [0.0], "cpu": [0.0], "ram": [0.0]})

        times = series["time"]
        cpu_used = series["cpu"]
        ram_used = series["ram"]

        cpu_cap = float(node.get("CPU", 0) or 0)
        ram_cap = float(node.get("RAM", 0) or 0)

        cpu_pct = [(value / cpu_cap * 100.0) if cpu_cap > 0 else 0.0 for value in cpu_used]
        ram_pct = [(value / ram_cap * 100.0) if ram_cap > 0 else 0.0 for value in ram_used]

        node_name = node.get("name", f"Nodo {node_id}")
        node_type = node.get("type", "unknown")
        node_role = node.get("role", "-")

        title_prefix = f"Nodo {node_id} - {node_name} ({node_type}/{node_role})"
        safe_name = _slugify(str(node_name))

        # CPU chart
        fig, ax = plt.subplots(figsize=(10.5, 4.6))
        ax.step(times, cpu_pct, where="post", linewidth=2.0, color="#e8590c", label="CPU (%)")
        ax.fill_between(times, cpu_pct, step="post", alpha=0.10, color="#e8590c")
        upper_cpu = max(100.0, min(250.0, max(cpu_pct + [0.0]) * 1.15 + 5.0))
        ax.set_ylim(0.0, upper_cpu)
        ax.axhline(100.0, linestyle="--", linewidth=1.0, color="#868e96", alpha=0.6)
        ax.grid(True, alpha=0.25)
        ax.set_title(f"{title_prefix}\nCapacidad CPU={cpu_cap:.0f} cores")
        ax.set_xlabel("Tiempo simulado (ut)")
        ax.set_ylabel("Uso de CPU (%)")
        ax.legend(loc="upper right")
        cpu_save_path = cpu_output_dir / f"node_{int(node_id):02d}_{safe_name}_cpu.png"
        fig.savefig(cpu_save_path, dpi=130, bbox_inches="tight")
        plt.close(fig)
        cpu_generated += 1

        # RAM chart
        fig, ax = plt.subplots(figsize=(10.5, 4.6))
        ax.step(times, ram_pct, where="post", linewidth=2.0, color="#1971c2", label="RAM (%)")
        ax.fill_between(times, ram_pct, step="post", alpha=0.10, color="#1971c2")
        upper_ram = max(100.0, min(250.0, max(ram_pct + [0.0]) * 1.15 + 5.0))
        ax.set_ylim(0.0, upper_ram)
        ax.axhline(100.0, linestyle="--", linewidth=1.0, color="#868e96", alpha=0.6)
        ax.grid(True, alpha=0.25)
        ax.set_title(f"{title_prefix}\nCapacidad RAM={ram_cap:.0f} MB")
        ax.set_xlabel("Tiempo simulado (ut)")
        ax.set_ylabel("Uso de RAM (%)")
        ax.legend(loc="upper right")
        ram_save_path = ram_output_dir / f"node_{int(node_id):02d}_{safe_name}_ram.png"
        fig.savefig(ram_save_path, dpi=130, bbox_inches="tight")
        plt.close(fig)
        ram_generated += 1

    return cpu_output_dir, cpu_generated, ram_output_dir, ram_generated


def analyze_results(results_path, nodes_info: dict):
    """
    Imprime un informe detallado a partir de los CSV de YAFS.

    Parameters
    ----------
    results_path : str | Path — directorio con sim_trace*.csv.
    nodes_info   : dict {node_id: {...}} con atributos de cada nodo.
    """
    try:
        import pandas as pd
    except ImportError:
        print("❌ pandas no instalado. Instálelo con: pip install pandas")
        return

    results_path = Path(results_path)

    print("\n" + "=" * 70)
    print("ANALISIS DE RESULTADOS — SMART CITY")
    print("=" * 70 + "\n")

    try:
        df_links    = pd.read_csv(results_path / "sim_trace_link.csv")
        df_messages = pd.read_csv(results_path / "sim_trace.csv")
    except FileNotFoundError as exc:
        print(f"❌ Archivo no encontrado: {exc}")
        return
    except Exception as exc:
        print(f"❌ Error leyendo CSV: {exc}")
        return

    print(f"Total de mensajes transmitidos : {len(df_links)}")
    print(f"Total de peticiones procesadas : {len(df_messages)}")

    if len(df_messages) == 0:
        print("  Sin datos de procesamiento.")
        return

    camera_nodes  = [n for n, a in nodes_info.items() if a["type"] == "edge"]
    gateway_nodes = [n for n, a in nodes_info.items() if a["type"] == "gateway"]
    fog_nodes     = [n for n, a in nodes_info.items() if a["type"] == "fog"]
    cloud_nodes   = [n for n, a in nodes_info.items() if a["type"] == "cloud"]

    # ── Por capa ──────────────────────────────────────────────────────────
    print("\n" + "-" * 70)
    print("ANÁLISIS POR CAPA")
    print("-" * 70)

    for label, icon, nodeset in [
        ("EDGE   (Ingestion)", "📷", camera_nodes),
        ("GATEWAY(Transito)", "🟢", gateway_nodes),
        ("FOG    (Procesamiento)", "🟠", fog_nodes),
        ("CLOUD  (Servicios)", "☁️ ", cloud_nodes),
    ]:
        subset = df_messages[df_messages["TOPO.dst"].isin(nodeset)]
        print(f"\n{icon} {label}:")
        print(f"   Mensajes procesados : {len(subset)}")
        if len(subset) > 0:
            latency = subset["time_out"].sub(subset["time_in"])
            print(f"   Latencia promedio   : {latency.mean():.2f} ut")
            print(f"   Latencia máxima     : {latency.max():.2f} ut")

    # ── Por flujo de aplicación ────────────────────────────────────────────
    print("\n" + "-" * 70)
    print("ANÁLISIS POR FLUJO")
    print("-" * 70)

    flow_labels = {
        "Urban_Video_Analytics": "App 1 — Urban_Video_Analytics",
        "Urban_Sensor_Climatology": "App 2 — Urban_Sensor_Climatology",
        "Platform_Lifecycle": "Shared — Platform_Lifecycle",
    }

    for app_id in df_messages["app"].unique():
        sub = df_messages[df_messages["app"] == app_id]
        latency = sub["time_out"].sub(sub["time_in"])
        trans   = sub["time_in"].sub(sub["time_reception"])
        label   = flow_labels.get(str(app_id), f"App {app_id}")
        print(f"\n{label}:")
        print(f"   Total de mensajes procesados  : {len(sub)}")
        print(f"   Latencia promedio (servicio)  : {latency.mean():.2f} ut")
        print(f"   Latencia máxima  (servicio)   : {latency.max():.2f} ut")
        print(f"   Tiempo transmisión promedio   : {trans.mean():.2f} ut")

    # ── Tráfico por tramo de red ───────────────────────────────────────────
    if len(df_links) > 0:
        print("\n" + "-" * 70)
        print("TRÁFICO POR TRAMO DE RED")
        print("-" * 70)

        def link_count(src_set, dst_set):
            return len(df_links[
                df_links["src"].isin(src_set) & df_links["dst"].isin(dst_set)
            ])

        eg = link_count(camera_nodes, gateway_nodes) + link_count(gateway_nodes, camera_nodes)
        gf = link_count(gateway_nodes, fog_nodes) + link_count(fog_nodes, gateway_nodes)
        cf = link_count(camera_nodes, fog_nodes) + link_count(fog_nodes, camera_nodes)
        fc = link_count(fog_nodes, cloud_nodes)  + link_count(cloud_nodes, fog_nodes)

        print(f"\n Edge ↔ Gateway : {eg:,} transmisiones")
        print(f" Gateway ↔ Fog  : {gf:,} transmisiones")
        print(f" Edge ↔ Fog     : {cf:,} transmisiones")
        print(f" Fog  ↔ Cloud : {fc:,} transmisiones")
        baseline_edge = eg if eg > 0 else cf
        if baseline_edge > 0:
            ratio = fc / baseline_edge
            print(f"   Relación Cloud/Edge        : {ratio:.2%} (reducción por inferencia)")

    # ── Top 5 nodos más activos ────────────────────────────────────────────
    print("\n" + "-" * 70)
    print("TOP 5 NODOS MÁS ACTIVOS")
    print("-" * 70 + "\n")

    for node, count in df_messages["TOPO.dst"].value_counts().head(5).items():
        info  = nodes_info.get(int(node), {})
        name  = info.get("name",  f"Nodo {node}")
        ntype = info.get("type",  "unknown")
        model = info.get("model", "")
        print(f"   {name} ({ntype} / {model}) : {count} mensajes")

    # ── Latencia end-to-end ────────────────────────────────────────────────
    if "time_reception" in df_messages.columns:
        print("\n" + "-" * 70)
        print("LATENCIA END-TO-END (cámara → resultado)")
        print("-" * 70)

        e2e = df_messages["time_out"] - df_messages["time_reception"]
        print(f"\n   Promedio : {e2e.mean():.2f} ut")
        print(f"   Mínima   : {e2e.min():.2f} ut")
        print(f"   Máxima   : {e2e.max():.2f} ut")
        print(f"   Desv. est: {e2e.std():.2f} ut")

        # Separar e2e por flujo si es posible
        for app_id, label in flow_labels.items():
            sub_e2e = df_messages[df_messages["app"] == app_id]
            if len(sub_e2e) > 0:
                fe2e = sub_e2e["time_out"] - sub_e2e["time_reception"]
                print(f"\n   {label}")
                print(f"     E2E promedio : {fe2e.mean():.2f} ut")
                print(f"     E2E máximo   : {fe2e.max():.2f} ut")

    # ── Uso CPU/RAM por nodo a lo largo del tiempo ───────────────────────
    print("\n" + "-" * 70)
    print("USO TEMPORAL DE CPU/RAM POR NODO")
    print("-" * 70)

    node_series, usage_rows = _build_usage_timeseries(df_messages, nodes_info)
    if usage_rows:
        usage_df = pd.DataFrame(usage_rows)
        output_dir = results_path / "resource_usage"
        output_dir.mkdir(parents=True, exist_ok=True)
        usage_csv_path = output_dir / "node_resource_usage_timeline.csv"
        usage_df.to_csv(usage_csv_path, index=False)

        cpu_dir, cpu_count, ram_dir, ram_count = _export_node_resource_charts(
            results_path,
            nodes_info,
            node_series,
        )

        print(f"\n   CSV temporal generado: {usage_csv_path}")
        if cpu_dir is not None:
            print(f"   Gráficas CPU         : {cpu_count} archivo(s) en {cpu_dir}")
            print(f"   Gráficas RAM         : {ram_count} archivo(s) en {ram_dir}")
    else:
        print("\n   No se pudo reconstruir la serie temporal de uso por nodo.")

    print("\n" + "=" * 70 + "\n")
