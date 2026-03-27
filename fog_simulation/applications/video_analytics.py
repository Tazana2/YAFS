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
        {"edge-video-ingestion-service":    {"Type": Application.TYPE_SOURCE}},
        {"edge-inference-service":           {"RAM": 4096,  "CPU_req": 2, "RAM_req": 4096,  "Type": Application.TYPE_MODULE}},
        {"tracking-and-event-service":       {"RAM": 3072,  "CPU_req": 1, "RAM_req": 3072,  "Type": Application.TYPE_MODULE}},
        {"video-stream-processing-service":  {"RAM": 8192,  "CPU_req": 4, "RAM_req": 8192,  "Type": Application.TYPE_MODULE}},
        {"storage-service":                  {"RAM": 16384, "CPU_req": 2, "RAM_req": 16384, "Type": Application.TYPE_MODULE}},
        {"api-and-access-service":           {"RAM": 4096,  "CPU_req": 1, "RAM_req": 4096,  "Type": Application.TYPE_MODULE}},
        {"visualization-service":            {"Type": Application.TYPE_SINK}},
        {"notification-service":             {"Type": Application.TYPE_SINK}},
        {"observability-service":            {"Type": Application.TYPE_SINK}},
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
