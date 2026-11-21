"""Prepare density values without Qt objects or color settings."""

import math

import numpy as np
from scipy.interpolate import griddata


def prepare_density(distances, azimuths, grid_size=10):
    """Preserve the existing count grid, interpolation, and normalization."""
    if (
        isinstance(grid_size, bool)
        or int(grid_size) != grid_size
        or grid_size < 2
    ):
        raise ValueError(
            "Density grid size must be an integer of at least two."
        )

    grid_size = int(grid_size)
    distances = tuple(float(value) for value in distances)
    azimuths = tuple(float(value) for value in azimuths)

    if not distances or len(distances) != len(azimuths):
        raise ValueError(
            "Distance and azimuth series must be nonempty and aligned."
        )

    if not all(
        math.isfinite(value)
        for values in (distances, azimuths)
        for value in values
    ):
        raise ValueError("Density inputs must be finite.")

    if min(distances) < 0:
        raise ValueError("Distances cannot be negative.")

    maximum = max(distances)

    if maximum <= 0:
        raise ValueError(
            "Density interpolation requires a positive distance."
        )

    counts = np.zeros((grid_size, grid_size), dtype=int)
    center = grid_size // 2

    for distance, azimuth in zip(distances, azimuths):
        theta = np.radians(azimuth)

        x = center + int(
            np.sin(theta) * distance * (center / maximum)
        )
        y = center - int(
            np.cos(theta) * distance * (center / maximum)
        )

        if x == grid_size:
            x -= 1

        if y == grid_size:
            y -= 1

        if 0 <= x < grid_size and 0 <= y < grid_size:
            counts[y, x] += 1

    rows, columns = np.nonzero(counts)
    values = counts[rows, columns]

    grid_x, grid_y = np.mgrid[0:grid_size, 0:grid_size]

    interpolated = griddata(
        points=(columns, rows),
        values=values,
        xi=(grid_x, grid_y),
        method="linear",
    )

    interpolated = np.transpose(interpolated)
    interpolated = np.nan_to_num(interpolated, nan=0)

    norm = np.log1p(np.maximum(interpolated, 0))
    span = np.ptp(norm)

    if span == 0 or np.isnan(span):
        span = 1

    norm = 255 * (norm - np.min(norm)) / span
    norm = np.clip(norm, 0, 255).astype(np.uint8)

    quartile = int(np.quantile(norm, 0.999))

    # Cached numeric values must not be modified by rendering.
    norm.setflags(write=False)

    return {
        "grid_size": grid_size,
        "norm": norm,
        "quartile": quartile,
    }