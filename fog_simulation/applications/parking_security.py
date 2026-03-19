"""
Flujo B — Seguridad / Video Continuo
======================================
Cámara → Fog (Passthrough) → Cloud (Storage de video).

Prioridad    : Alta (no se pueden perder frames).
Carga de Red : Alta (stream constante ~4 Mbps por cámara).

Módulos
-------
CameraStream      [SOURCE] — Genera chunks de video H.264 en la cámara IP.
VideoPassthrough  [MODULE] — Re-encapsula y enruta el chunk; mínimo cómputo.
CloudVideoStorage [SINK]   — Escribe el chunk en almacenamiento persistente.

Parámetros derivados de los CSV de sim_params
---------------------------------------------
* Instrucciones de Passthrough (re-encapsulado) en RPi4:
    RPi4 IPT = 6 000 MIPS
    Uso CPU = 15–20 % de la carga total → ~67 ms
    instrucciones = 0.067 × 6 000e6 ≈ 400 × 10⁶

* Instrucciones de escritura a storage cloud:
    Cloud IPT = 100 000 MIPS
    Latencia escritura disco = 20 ms (mid de 10–30 ms)
    instrucciones = 0.02 × 100 000e6 = 2 000 × 10⁶

* Tamaño de chunk de video (1 segundo @ 4 Mbps):
    4 000 000 bps × 1 s / 8 = 500 000 bytes (500 KB)
    → modela la alta carga de red del stream continuo

* No se aplica selectividad parcial: threshold = 1.0
  (alta prioridad, ningún segundo de video puede perderse).
"""

from yafs.application import Application, Message, fractional_selectivity


def create_parking_security_app() -> Application:
    """Crea la aplicación Flujo B: video passthrough + almacenamiento cloud."""
    app = Application(name="Parking_Security")

    app.set_modules([
        {"CameraStream":      {"Type": Application.TYPE_SOURCE}},
        {"VideoPassthrough":  {"RAM": 200, "Type": Application.TYPE_MODULE}},
        {"CloudVideoStorage": {"Type": Application.TYPE_SINK}},
    ])

    # ── Cámara → Fog: chunk de video H.264 crudo ──────────────────────────
    # bytes   : 500 KB (1 segundo de video @ 4 Mbps)
    # instr   : 400 × 10⁶ → modela re-encapsulado (~67 ms en RPi4)
    m_chunk = Message(
        "M.VideoChunk",
        "CameraStream",
        "VideoPassthrough",
        instructions=400 * 10**6,
        bytes=500_000,
    )

    # ── Fog → Cloud: mismo chunk re-encapsulado para storage ──────────────
    # bytes   : 500 KB (sin transcodificación, alta carga de red)
    # instr   : 2 000 × 10⁶ → modela los 20 ms de escritura en disco cloud
    m_upload = Message(
        "M.UploadChunk",
        "VideoPassthrough",
        "CloudVideoStorage",
        instructions=2000 * 10**6,
        bytes=500_000,
    )

    app.add_source_messages(m_chunk)

    # Prioridad Alta: 100 % de los chunks se transmiten y almacenan
    app.add_service_module(
        "VideoPassthrough",
        m_chunk,
        m_upload,
        fractional_selectivity,
        threshold=1.0,
    )

    return app
