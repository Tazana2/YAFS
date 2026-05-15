"""
Servicios de ciclo de vida de plataforma.

Cobertura de microservicios del caso de uso:
15. mlops-platform-service [MODULE]
16. deployment-and-distribution-service [MODULE]
17. simulation-service [SOURCE]
11. api-and-access-service [MODULE]
14. observability-service [SINK]
"""

from yafs.application import Application, Message, fractional_selectivity


def create_platform_lifecycle_app() -> Application:
    """Crea una app de control para modelar entrenamiento, despliegue y observabilidad."""
    app = Application(name="Platform_Lifecycle")

    app.set_modules([
        {"simulation-service": {
            "Type": Application.TYPE_SOURCE,
            "CPU_req": 0,
            "RAM_req": 0,
            "BW_req": 25,
            "service_class": "simulation-feed",
            "slo_ms_p99": 5000,
            "allowed_layers": ["cloud"],
            "preferred_role": "mlops",
            "priority": 20,
            "cooldown_windows": 10,
        }},
        {"mlops-platform-service": {
            "RAM": 32768,
            "CPU_req": 8,
            "RAM_req": 32768,
            "BW_req": 60,
            "Type": Application.TYPE_MODULE,
            "service_class": "platform-mlops",
            "slo_ms_p99": 10000,
            "allowed_layers": ["cloud"],
            "preferred_role": "mlops",
            "priority": 20,
            "cooldown_windows": 12,
        }},
        {"deployment-and-distribution-service": {
            "RAM": 2048,
            "CPU_req": 2,
            "RAM_req": 2048,
            "BW_req": 50,
            "Type": Application.TYPE_MODULE,
            "service_class": "platform-deployment",
            "slo_ms_p99": 5000,
            "allowed_layers": ["cloud"],
            "preferred_role": "deployment",
            "priority": 30,
            "cooldown_windows": 10,
        }},
        {"api-and-access-service": {
            "RAM": 4096,
            "CPU_req": 1,
            "RAM_req": 4096,
            "BW_req": 20,
            "Type": Application.TYPE_MODULE,
            "service_class": "platform-api",
            "slo_ms_p99": 2000,
            "allowed_layers": ["cloud"],
            "preferred_role": "api_access",
            "priority": 30,
            "cooldown_windows": 8,
        }},
        {"observability-service": {
            "Type": Application.TYPE_SINK,
            "CPU_req": 0,
            "RAM_req": 0,
            "BW_req": 12,
            "service_class": "observability",
            "slo_ms_p99": 5000,
            "allowed_layers": ["cloud"],
            "preferred_role": "observability",
            "priority": 20,
            "cooldown_windows": 10,
        }},
    ])

    m_training_batch = Message(
        "M.Platform.TrainingBatch",
        "simulation-service",
        "mlops-platform-service",
        instructions=1400 * 10**6,
        bytes=200_000,
    )

    m_model_release = Message(
        "M.Platform.ModelRelease",
        "mlops-platform-service",
        "deployment-and-distribution-service",
        instructions=500 * 10**6,
        bytes=120_000,
    )

    m_deploy_event = Message(
        "M.Platform.DeployEvent",
        "deployment-and-distribution-service",
        "api-and-access-service",
        instructions=300 * 10**6,
        bytes=20_000,
    )

    m_platform_telemetry = Message(
        "M.Platform.Telemetry",
        "api-and-access-service",
        "observability-service",
        instructions=100 * 10**6,
        bytes=5_000,
    )

    app.add_source_messages(m_training_batch)

    app.add_service_module(
        "mlops-platform-service",
        m_training_batch,
        m_model_release,
        fractional_selectivity,
        threshold=1.0,
    )
    app.add_service_module(
        "deployment-and-distribution-service",
        m_model_release,
        m_deploy_event,
        fractional_selectivity,
        threshold=1.0,
    )
    app.add_service_module(
        "api-and-access-service",
        m_deploy_event,
        m_platform_telemetry,
        fractional_selectivity,
        threshold=1.0,
    )

    return app
