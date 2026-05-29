"""
fog_simulation — Simulacion urbana multi-app con scheduler K8s sobre YAFS.
"""

from fog_simulation.topology      import create_edge_fog_cloud_topology
from fog_simulation.applications  import (
    create_parking_intelligence_app,
    create_parking_security_app,
    create_video_analytics_app,
    create_sensor_climatology_app,
    create_platform_lifecycle_app,
)
from fog_simulation.recording     import SimulationRecorder
from fog_simulation.visualization import visualize_topology, create_deployment_diagram
from fog_simulation.simulation    import run_simulation, KubernetesDefaultScheduler
from fog_simulation.simulation    import LatencyResourceAwareScheduler
from fog_simulation.analysis      import analyze_results

__all__ = [
    # topology
    "create_edge_fog_cloud_topology",
    # applications
    "create_parking_intelligence_app",
    "create_parking_security_app",
    "create_video_analytics_app",
    "create_sensor_climatology_app",
    "create_platform_lifecycle_app",
    # infrastructure
    "SimulationRecorder",
    "visualize_topology",
    "create_deployment_diagram",
    # simulation
    "run_simulation",
    "KubernetesDefaultScheduler",
    "LatencyResourceAwareScheduler",
    # analysis
    "analyze_results",
]
