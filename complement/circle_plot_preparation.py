"""Prepare reusable circle directions without Qt objects or colors."""

import math
from collections import Counter


def prepare_circle_geometry(distances, azimuths):
    """Prepare unit-circle stacking and distance-vector directions once."""
    distances = tuple(
        float(value) for value in distances
    )
    azimuths = tuple(
        float(value) for value in azimuths
    )

    if not distances or len(distances) != len(azimuths):
        raise ValueError(
            "Distance and azimuth series must be nonempty and aligned."
        )

    if not all(
        math.isfinite(value)
        for values in (distances, azimuths)
        for value in values
    ):
        raise ValueError("Circle inputs must be finite.")

    if min(distances) < 0:
        raise ValueError("Distances cannot be negative.")

    occurrences = Counter()
    unit = []
    radial = []

    for distance, azimuth in zip(distances, azimuths):
        rounded = round(azimuth, 0)

        previous = occurrences[rounded]
        occurrences[rounded] += 1

        unit_angle = rounded * math.pi / 180
        radial_angle = azimuth * math.pi / 180

        unit.append(
            (
                math.sin(unit_angle),
                math.cos(unit_angle),
                previous,
            )
        )

        radial.append(
            (
                math.sin(radial_angle),
                math.cos(radial_angle),
                distance,
            )
        )

    return {
        "unit": tuple(unit),
        "radial": tuple(radial),
        "max_distance": max(distances),
    }