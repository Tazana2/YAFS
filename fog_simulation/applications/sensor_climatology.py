"""
Aplicacion 2 — Recoleccion de Sensores y Climatologia.

Cobertura de microservicios del caso de uso:
5. edge-sensor-ingestion-service [SOURCE]
6. edge-sensor-preprocessing-service [MODULE]
7. climatology-integration-service [SOURCE]
8. sensor-stream-processing-service [MODULE]
9. sensor-prediction-service [MODULE]
10. storage-service [MODULE]
11. api-and-access-service [MODULE]
12. visualization-service [SINK]
13. notification-service [SINK]
14. observability-service [SINK]
"""

from yafs.application import Application, Message, fractional_selectivity


def create_sensor_climatology_app() -> Application:
    """Crea la aplicacion de sensores con enriquecimiento climatologico."""
    app = Application(name="Urban_Sensor_Climatology")

    app.set_modules([
        {"edge-sensor-ingestion-service":      {"Type": Application.TYPE_SOURCE}},
        {"climatology-integration-service":    {"Type": Application.TYPE_SOURCE}},
        {"edge-sensor-preprocessing-service": {"RAM": 1024,  "CPU_req": 1, "RAM_req": 1024,  "Type": Application.TYPE_MODULE}},
        {"sensor-stream-processing-service":  {"RAM": 4096,  "CPU_req": 2, "RAM_req": 4096,  "Type": Application.TYPE_MODULE}},
        {"sensor-prediction-service":         {"RAM": 8192,  "CPU_req": 4, "RAM_req": 8192,  "Type": Application.TYPE_MODULE}},
        {"storage-service":                   {"RAM": 16384, "CPU_req": 2, "RAM_req": 16384, "Type": Application.TYPE_MODULE}},
        {"api-and-access-service":            {"RAM": 4096,  "CPU_req": 1, "RAM_req": 4096,  "Type": Application.TYPE_MODULE}},
        {"visualization-service":             {"Type": Application.TYPE_SINK}},
        {"notification-service":              {"Type": Application.TYPE_SINK}},
        {"observability-service":             {"Type": Application.TYPE_SINK}},
    ])

    m_sensor_raw = Message(
        "M.Sensor.Batch.Raw",
        "edge-sensor-ingestion-service",
        "edge-sensor-preprocessing-service",
        instructions=150 * 10**6,
        bytes=12_000,
    )

    m_sensor_clean = Message(
        "M.Sensor.Batch.Clean",
        "edge-sensor-preprocessing-service",
        "sensor-stream-processing-service",
        instructions=200 * 10**6,
        bytes=8_000,
    )

    m_climate_sync = Message(
        "M.Climate.Sync",
        "climatology-integration-service",
        "sensor-stream-processing-service",
        instructions=120 * 10**6,
        bytes=12_000,
    )

    m_sensor_agg = Message(
        "M.Sensor.Aggregates",
        "sensor-stream-processing-service",
        "sensor-prediction-service",
        instructions=450 * 10**6,
        bytes=40_000,
    )

    m_sensor_metrics = Message(
        "M.Sensor.Metrics",
        "sensor-stream-processing-service",
        "storage-service",
        instructions=300 * 10**6,
        bytes=60_000,
    )

    m_sensor_alert = Message(
        "M.Sensor.Alert",
        "sensor-stream-processing-service",
        "notification-service",
        instructions=100 * 10**6,
        bytes=4_000,
    )

    m_prediction = Message(
        "M.Sensor.Prediction",
        "sensor-prediction-service",
        "storage-service",
        instructions=700 * 10**6,
        bytes=8_000,
    )

    m_api_payload = Message(
        "M.Sensor.ApiPayload",
        "storage-service",
        "api-and-access-service",
        instructions=300 * 10**6,
        bytes=80_000,
    )

    m_dashboard = Message(
        "M.Sensor.Dashboard",
        "api-and-access-service",
        "visualization-service",
        instructions=200 * 10**6,
        bytes=200_000,
    )

    m_telemetry = Message(
        "M.Sensor.Telemetry",
        "sensor-stream-processing-service",
        "observability-service",
        instructions=100 * 10**6,
        bytes=4_000,
    )

    app.add_source_messages(m_sensor_raw)
    app.add_source_messages(m_climate_sync)

    app.add_service_module(
        "edge-sensor-preprocessing-service",
        m_sensor_raw,
        m_sensor_clean,
        fractional_selectivity,
        threshold=0.95,
    )
    app.add_service_module(
        "sensor-stream-processing-service",
        m_sensor_clean,
        m_sensor_agg,
        fractional_selectivity,
        threshold=1.0,
    )
    app.add_service_module(
        "sensor-stream-processing-service",
        m_climate_sync,
        m_sensor_metrics,
        fractional_selectivity,
        threshold=1.0,
    )
    app.add_service_module(
        "sensor-stream-processing-service",
        m_sensor_clean,
        m_sensor_alert,
        fractional_selectivity,
        threshold=0.15,
    )
    app.add_service_module(
        "sensor-stream-processing-service",
        m_sensor_clean,
        m_telemetry,
        fractional_selectivity,
        threshold=1.0,
    )
    app.add_service_module(
        "sensor-prediction-service",
        m_sensor_agg,
        m_prediction,
        fractional_selectivity,
        threshold=1.0,
    )
    app.add_service_module(
        "storage-service",
        m_prediction,
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
