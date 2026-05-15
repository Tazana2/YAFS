"""
Aplicación IoT principal:
  SensorReader → EdgeProcessor → FogAggregator → CloudAnalytics

Flujo:
  - Sensor genera datos (M.SensorData) en cada Raspberry Pi.
  - EdgeProcessor filtra el 80 % y reenvía datos procesados.
  - FogAggregator agrega el 30 % y sube al cloud.
  - CloudAnalytics es el módulo sumidero (SINK).
"""

from yafs.application import Application, Message, fractional_selectivity


def create_iot_application() -> Application:
    """Crea y devuelve la aplicación IoT de monitoreo de sensores."""
    app = Application(name="IoT_Monitoring")

    app.set_modules([
        {"SensorReader": {
            "Type": Application.TYPE_SOURCE,
            "CPU_req": 0,
            "RAM_req": 0,
            "BW_req": 2,
            "service_class": "iot-sensor-ingestion",
            "slo_ms_p99": 1000,
            "allowed_layers": ["edge"],
            "preferred_role": "sensor_ingestion",
            "priority": 55,
            "cooldown_windows": 3,
        }},
        {"EdgeProcessor": {
            "RAM": 100,
            "CPU_req": 1,
            "RAM_req": 100,
            "BW_req": 8,
            "Type": Application.TYPE_MODULE,
            "service_class": "iot-edge-processing",
            "slo_ms_p99": 800,
            "allowed_layers": ["edge", "fog"],
            "preferred_role": "sensor_ingestion",
            "priority": 60,
            "cooldown_windows": 3,
        }},
        {"FogAggregator": {
            "RAM": 500,
            "CPU_req": 1,
            "RAM_req": 500,
            "BW_req": 12,
            "Type": Application.TYPE_MODULE,
            "service_class": "iot-fog-aggregation",
            "slo_ms_p99": 1500,
            "allowed_layers": ["fog"],
            "preferred_role": "sensor_processing",
            "priority": 50,
            "cooldown_windows": 5,
        }},
        {"CloudAnalytics": {
            "Type": Application.TYPE_SINK,
            "CPU_req": 0,
            "RAM_req": 0,
            "BW_req": 10,
            "service_class": "iot-cloud-analytics",
            "slo_ms_p99": 3000,
            "allowed_layers": ["cloud"],
            "preferred_role": "storage",
            "priority": 40,
            "cooldown_windows": 8,
        }},
    ])

    # Sensor → Edge: lectura cruda del sensor (500 B, 10 M instrucciones)
    m1 = Message(
        "M.SensorData", "SensorReader", "EdgeProcessor",
        instructions=10 * 10**6, bytes=500,
    )

    # Edge → Fog: datos procesados y filtrados (2 KB, 50 M instrucciones)
    m2 = Message(
        "M.ProcessedData", "EdgeProcessor", "FogAggregator",
        instructions=50 * 10**6, bytes=2000,
    )

    # Fog → Cloud: resumen agregado (5 KB, 100 M instrucciones)
    m3 = Message(
        "M.AggregatedData", "FogAggregator", "CloudAnalytics",
        instructions=100 * 10**6, bytes=5000,
    )

    app.add_source_messages(m1)

    # 80 % de lecturas pasan al Fog (se descartan el 20 % en edge)
    app.add_service_module("EdgeProcessor", m1, m2,
                           fractional_selectivity, threshold=0.8)
    # 30 % de los datos agregados suben al cloud
    app.add_service_module("FogAggregator", m2, m3,
                           fractional_selectivity, threshold=0.3)

    return app
