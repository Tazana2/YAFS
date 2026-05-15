"""
Aplicacion 1 — Video Streaming y Analitica Urbana.

Cobertura de microservicios del caso de uso:
1. edge-video-ingestion-service [SOURCE]
2. edge-inference-service [MODULE]
3. tracking-and-event-service [MODULE]
4. video-stream-processing-service [MODULE]
10. storage-service [MODULE]
11. api-and-access-service [MODULE]
12. visualization-service [SINK]
13. notification-service [SINK]
14. observability-service [SINK]
"""

from yafs.application import Application, Message, fractional_selectivity


def create_video_analytics_app() -> Application:
    """Crea la aplicacion de video con cadena Edge/Fog y servicios compartidos."""
    app = Application(name="Urban_Video_Analytics")

    app.set_modules([
        {"edge-video-ingestion-service": {
            "Type": Application.TYPE_SOURCE,
            "CPU_req": 0,
            "RAM_req": 0,
            "BW_req": 120,
            "service_class": "video-ingestion",
            "slo_ms_p99": 120,
            "allowed_layers": ["edge"],
            "preferred_role": "video_ingestion",
            "priority": 95,
            "cooldown_windows": 2,
        }},
        {"edge-inference-service": {
            "RAM": 4096,
            "CPU_req": 2,
            "RAM_req": 4096,
            "BW_req": 180,
            "Type": Application.TYPE_MODULE,
            "service_class": "video-inference",
            "slo_ms_p99": 90,
            "allowed_layers": ["fog"],
            "preferred_role": "video_processing",
            "priority": 100,
            "cooldown_windows": 3,
        }},
        {"tracking-and-event-service": {
            "RAM": 3072,
            "CPU_req": 1,
            "RAM_req": 3072,
            "BW_req": 80,
            "Type": Application.TYPE_MODULE,
            "service_class": "video-eventing",
            "slo_ms_p99": 120,
            "allowed_layers": ["fog"],
            "preferred_role": "video_processing",
            "priority": 90,
            "cooldown_windows": 3,
        }},
        {"video-stream-processing-service": {
            "RAM": 8192,
            "CPU_req": 2,
            "RAM_req": 4096,
            "BW_req": 220,
            "Type": Application.TYPE_MODULE,
            "service_class": "video-stream-processing",
            "slo_ms_p99": 150,
            "allowed_layers": ["fog"],
            "preferred_role": "video_processing",
            "priority": 95,
            "cooldown_windows": 3,
        }},
        {"storage-service": {
            "RAM": 16384,
            "CPU_req": 2,
            "RAM_req": 16384,
            "BW_req": 140,
            "Type": Application.TYPE_MODULE,
            "service_class": "video-storage",
            "slo_ms_p99": 350,
            "allowed_layers": ["cloud"],
            "preferred_role": "storage",
            "priority": 70,
            "cooldown_windows": 6,
        }},
        {"api-and-access-service": {
            "RAM": 4096,
            "CPU_req": 1,
            "RAM_req": 4096,
            "BW_req": 45,
            "Type": Application.TYPE_MODULE,
            "service_class": "video-api",
            "slo_ms_p99": 250,
            "allowed_layers": ["cloud"],
            "preferred_role": "api_access",
            "priority": 65,
            "cooldown_windows": 5,
        }},
        {"visualization-service": {
            "Type": Application.TYPE_SINK,
            "CPU_req": 0,
            "RAM_req": 0,
            "BW_req": 35,
            "service_class": "visualization",
            "slo_ms_p99": 500,
            "allowed_layers": ["cloud"],
            "preferred_role": "visualization",
            "priority": 45,
            "cooldown_windows": 6,
        }},
        {"notification-service": {
            "Type": Application.TYPE_SINK,
            "CPU_req": 0,
            "RAM_req": 0,
            "BW_req": 10,
            "service_class": "notification",
            "slo_ms_p99": 300,
            "allowed_layers": ["cloud"],
            "preferred_role": "notification",
            "priority": 85,
            "cooldown_windows": 4,
        }},
        {"observability-service": {
            "Type": Application.TYPE_SINK,
            "CPU_req": 0,
            "RAM_req": 0,
            "BW_req": 15,
            "service_class": "observability",
            "slo_ms_p99": 1000,
            "allowed_layers": ["cloud"],
            "preferred_role": "observability",
            "priority": 30,
            "cooldown_windows": 8,
        }},
    ])

    # Batches preprocesados de 4-8 frames comprimidos.
    m_video_batch = Message(
        "M.Video.Batch",
        "edge-video-ingestion-service",
        "edge-inference-service",
        instructions=800 * 10**6,
        bytes=500_000,
    )

    m_detections = Message(
        "M.Video.Detections",
        "edge-inference-service",
        "tracking-and-event-service",
        instructions=1200 * 10**6,
        bytes=45_000,
    )

    m_tracks = Message(
        "M.Video.Tracks",
        "tracking-and-event-service",
        "video-stream-processing-service",
        instructions=500 * 10**6,
        bytes=20_000,
    )

    m_stream_metrics = Message(
        "M.Video.StreamMetrics",
        "video-stream-processing-service",
        "storage-service",
        instructions=700 * 10**6,
        bytes=100_000,
    )

    m_event_alert = Message(
        "M.Video.EventAlert",
        "video-stream-processing-service",
        "notification-service",
        instructions=100 * 10**6,
        bytes=4_000,
    )

    m_telemetry = Message(
        "M.Video.Telemetry",
        "video-stream-processing-service",
        "observability-service",
        instructions=100 * 10**6,
        bytes=5_000,
    )

    m_api_payload = Message(
        "M.Video.ApiPayload",
        "storage-service",
        "api-and-access-service",
        instructions=400 * 10**6,
        bytes=120_000,
    )

    m_dashboard = Message(
        "M.Video.Dashboard",
        "api-and-access-service",
        "visualization-service",
        instructions=300 * 10**6,
        bytes=240_000,
    )

    app.add_source_messages(m_video_batch)

    app.add_service_module(
        "edge-inference-service",
        m_video_batch,
        m_detections,
        fractional_selectivity,
        threshold=1.0,
    )
    app.add_service_module(
        "tracking-and-event-service",
        m_detections,
        m_tracks,
        fractional_selectivity,
        threshold=1.0,
    )
    app.add_service_module(
        "video-stream-processing-service",
        m_tracks,
        m_stream_metrics,
        fractional_selectivity,
        threshold=1.0,
    )
    # El stream processing emite adicionalmente alertas y telemetria.
    app.add_service_module(
        "video-stream-processing-service",
        m_tracks,
        m_event_alert,
        fractional_selectivity,
        threshold=0.25,
    )
    app.add_service_module(
        "video-stream-processing-service",
        m_tracks,
        m_telemetry,
        fractional_selectivity,
        threshold=1.0,
    )
    app.add_service_module(
        "storage-service",
        m_stream_metrics,
        m_api_payload,
        fractional_selectivity,
        threshold=1.0,
    )
    app.add_service_module(
        "api-and-access-service",
        m_api_payload,
        m_dashboard,
        fractional_selectivity,
        threshold=1.0,
    )

    return app
