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
        {"SensorReader":  {"Type": Application.TYPE_SOURCE}},
        {"EdgeProcessor": {"RAM": 100, "Type": Application.TYPE_MODULE}},
        {"FogAggregator": {"RAM": 500, "Type": Application.TYPE_MODULE}},
        {"CloudAnalytics": {"Type": Application.TYPE_SINK}},
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
