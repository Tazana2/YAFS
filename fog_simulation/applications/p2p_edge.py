"""
Aplicación P2P: comunicación directa entre Raspberry Pi vecinas.

Flujo:
  LocalSensor → PeerProcessor → LocalActuator

El 100 % de los datos locales desencadena un comando al actuador vecino.
"""

from yafs.application import Application, Message, fractional_selectivity


def create_p2p_edge_application() -> Application:
    """Crea y devuelve la aplicación de comunicación P2P entre nodos edge."""
    app = Application(name="P2P_EdgeComm")

    app.set_modules([
        {"LocalSensor":   {"Type": Application.TYPE_SOURCE}},
        {"PeerProcessor": {"RAM": 50, "Type": Application.TYPE_MODULE}},
        {"LocalActuator": {"Type": Application.TYPE_SINK}},
    ])

    # Sensor local → procesador (300 B, 5 M instrucciones)
    m1 = Message(
        "M.LocalData", "LocalSensor", "PeerProcessor",
        instructions=5 * 10**6, bytes=300,
    )

    # Procesador → actuador local (200 B, 5 M instrucciones)
    m2 = Message(
        "M.LocalCommand", "PeerProcessor", "LocalActuator",
        instructions=5 * 10**6, bytes=200,
    )

    app.add_source_messages(m1)
    app.add_service_module("PeerProcessor", m1, m2,
                           fractional_selectivity, threshold=1.0)

    return app
