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
        {"simulation-service": {"Type": Application.TYPE_SOURCE}},
        {"mlops-platform-service": {"RAM": 32768, "Type": Application.TYPE_MODULE}},
        {"deployment-and-distribution-service": {"RAM": 2048, "Type": Application.TYPE_MODULE}},
        {"api-and-access-service": {"RAM": 4096, "Type": Application.TYPE_MODULE}},
        {"observability-service": {"Type": Application.TYPE_SINK}},
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
