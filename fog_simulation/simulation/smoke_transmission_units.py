"""Smoke checks for Message.bytes transmission unit convention.

Run with:
    python -m fog_simulation.simulation.smoke_transmission_units
"""

from yafs.core import BYTES_TO_BITS, transmission_time_from_bytes


def main() -> None:
    payload_bytes = 80 * 1024
    bandwidth_mbps = 10
    expected = (payload_bytes * BYTES_TO_BITS) / (bandwidth_mbps * 1000000.0)
    observed = transmission_time_from_bytes(payload_bytes, bandwidth_mbps)

    assert abs(observed - expected) < 1e-12
    assert abs(observed - 0.065536) < 1e-12

    print("Transmission unit smoke checks passed.")


if __name__ == "__main__":
    main()
