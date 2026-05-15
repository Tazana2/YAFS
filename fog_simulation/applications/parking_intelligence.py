"""
Flujo A — Inteligencia de Parqueadero
======================================
Cámara → Fog (YOLOv8) → Cloud (Registro JSON).

Prioridad : Media.
Carga CPU : Alta (inferencia YOLOv8n ~450 ms/frame en Raspberry Pi 4).

Módulos
-------
CameraCapture   [SOURCE]  — Genera frames de 720p en la cámara IP.
YOLOv8_Inference [MODULE] — Detecta vehículos; produce JSON con celdas ocupadas/vacias.
CloudRegistry    [SINK]   — Registra el resultado en la base de datos cloud.

Parámetros derivados de los CSV de sim_params
---------------------------------------------
* Instrucciones de inferencia:
    RPi4 IPT = 6 000 MIPS = 6 000 × 10⁶ inst/s
    Latencia YOLOv8n = 450 ms → instrucciones = 0.45 × 6 000e6 = 2 700 × 10⁶

* Instrucciones de escritura DB:
    Cloud IPT = 100 000 MIPS
    Latencia DB write = 10 ms → instrucciones = 0.01 × 100 000e6 = 1 000 × 10⁶

* Tamaño de frame H.264 (720p @ 5 Mbps, 30 fps):
    5 000 000 bps / 30 fps / 8 = ~20 833 bytes ≈ 20 000 bytes

* Resultado JSON (id_celda + estado + timestamp): ~2 000 bytes
"""

from yafs.application import Application, Message, fractional_selectivity


def create_parking_intelligence_app() -> Application:
    """Crea la aplicación Flujo A: inferencia YOLOv8 + registro en cloud."""
    app = Application(name="Parking_Intelligence")

    app.set_modules([
        {"CameraCapture": {
            "Type": Application.TYPE_SOURCE,
            "CPU_req": 0,
            "RAM_req": 0,
            "BW_req": 35,
            "service_class": "parking-video-ingestion",
            "slo_ms_p99": 250,
            "allowed_layers": ["edge"],
            "preferred_role": "video_ingestion",
            "priority": 85,
            "cooldown_windows": 2,
        }},
        {"YOLOv8_Inference": {
            "RAM": 700,
            "CPU_req": 2,
            "RAM_req": 700,
            "BW_req": 70,
            "Type": Application.TYPE_MODULE,
            "service_class": "parking-inference",
            "slo_ms_p99": 500,
            "allowed_layers": ["fog"],
            "preferred_role": "video_processing",
            "priority": 85,
            "cooldown_windows": 3,
        }},
        {"CloudRegistry": {
            "Type": Application.TYPE_SINK,
            "CPU_req": 0,
            "RAM_req": 0,
            "BW_req": 8,
            "service_class": "parking-registry",
            "slo_ms_p99": 1000,
            "allowed_layers": ["cloud"],
            "preferred_role": "storage",
            "priority": 60,
            "cooldown_windows": 5,
        }},
    ])

    # ── Cámara → Fog: frame H.264 para inferencia ──────────────────────────
    # bytes   : ~20 KB (frame comprimido 720p H.264 @ 5 Mbps / 30 fps)
    # instr   : 2 700 × 10⁶ → modela los 450 ms de YOLOv8n en RPi4
    m_frame = Message(
        "M.VideoFrame",
        "CameraCapture",
        "YOLOv8_Inference",
        instructions=2700 * 10**6,
        bytes=20_000,
    )

    # ── Fog → Cloud: resultado JSON (celdas ocupadas/vacías) ───────────────
    # bytes   : 2 KB (JSON estructurado con estado del parqueadero)
    # instr   : 1 000 × 10⁶ → modela los 10 ms de escritura en DB cloud
    m_result = Message(
        "M.InferenceResult",
        "YOLOv8_Inference",
        "CloudRegistry",
        instructions=1000 * 10**6,
        bytes=2_000,
    )

    app.add_source_messages(m_frame)

    # Todos los frames procesados van al cloud (selectividad = 1.0)
    app.add_service_module(
        "YOLOv8_Inference",
        m_frame,
        m_result,
        fractional_selectivity,
        threshold=1.0,
    )

    return app
