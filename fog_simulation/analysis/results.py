"""
Análisis de resultados — Sistema de Parqueaderos.

Lee los CSV generados por YAFS (sim_trace.csv y sim_trace_link.csv) y
produce un informe desglosado por capa, por flujo y métricas end-to-end.

Flujos monitorizados
--------------------
  Flujo A (Parking_Intelligence) : Cámara → YOLOv8_Fog → CloudRegistry
  Flujo B (Parking_Security)     : Cámara → Passthrough → CloudVideoStorage
"""

from pathlib import Path


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
    print("ANÁLISIS DE RESULTADOS — PARQUEADERO")
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

    print(f"📊 Total de mensajes transmitidos : {len(df_links)}")
    print(f"📊 Total de peticiones procesadas : {len(df_messages)}")

    if len(df_messages) == 0:
        print("⚠️  Sin datos de procesamiento.")
        return

    camera_nodes = [n for n, a in nodes_info.items() if a["type"] == "edge"]
    fog_nodes    = [n for n, a in nodes_info.items() if a["type"] == "fog"]
    cloud_nodes  = [n for n, a in nodes_info.items() if a["type"] == "cloud"]

    # ── Por capa ──────────────────────────────────────────────────────────
    print("\n" + "-" * 70)
    print("ANÁLISIS POR CAPA")
    print("-" * 70)

    for label, icon, nodeset in [
        ("EDGE   (Cámaras IP)",     "📷", camera_nodes),
        ("FOG    (Raspberry Pi 4)", "🟠", fog_nodes),
        ("CLOUD  (Servidores)",     "☁️ ", cloud_nodes),
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
        "Parking_Intelligence": "Flujo A — Inteligencia (YOLOv8 → CloudRegistry)",
        "Parking_Security":     "Flujo B — Seguridad (Passthrough → VideoStorage)",
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

        cf = link_count(camera_nodes, fog_nodes) + link_count(fog_nodes, camera_nodes)
        fc = link_count(fog_nodes, cloud_nodes)  + link_count(cloud_nodes, fog_nodes)

        print(f"\n📡 Cámara ↔ RPi4  (Edge→Fog)  : {cf:,} transmisiones  ← video crudo + frames")
        print(f"📡 RPi4   ↔ Cloud (Fog→Cloud) : {fc:,} transmisiones  ← JSON + video almacenado")
        if cf > 0:
            ratio = fc / cf
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

    print("\n" + "=" * 70 + "\n")
