import numpy as np
from scipy.special import i0e


def prepare_circular_kde_epoch(
    azimuths,
    ratios,
    kappa,
    bands,
    grid_size=1440,
):
    """Prepare color-independent circular density contributions."""
    azimuths = np.asarray(azimuths, dtype=float)
    ratios = np.asarray(ratios, dtype=float)

    if (
        azimuths.ndim != 1
        or ratios.shape != azimuths.shape
        or azimuths.size == 0
    ):
        raise ValueError(
            "Epochs and azimuths must be nonempty aligned vectors."
        )

    if (
        not np.isfinite(azimuths).all()
        or not np.isfinite(ratios).all()
    ):
        raise ValueError("Epochs and azimuths must be finite.")

    if np.any((ratios < 0.0) | (ratios > 1.0)):
        raise ValueError(
            "Normalized epochs must belong to [0, 1]."
        )

    if not np.isfinite(kappa) or not 0 <= kappa <= 1000:
        raise ValueError("Kappa must belong to [0, 1000].")

    if not 1 <= bands <= 64 or grid_size < 72:
        raise ValueError(
            "Use 1–64 time bands and at least 72 angular points."
        )

    theta = np.linspace(
        0.0,
        2.0 * np.pi,
        grid_size,
        endpoint=False,
    )
    angles = np.deg2rad(azimuths % 360.0)

    indices = np.minimum(
        (ratios * bands).astype(int),
        bands - 1,
    )

    contributions = np.zeros(
        (bands, grid_size),
        dtype=float,
    )
    denominator = (
        2.0 * np.pi * i0e(kappa) * angles.size
    )

    # Limit temporary arrays without approximating the kernel sum.
    for band in range(bands):
        selected = angles[indices == band]

        for first in range(0, selected.size, 256):
            difference = (
                theta[:, None]
                - selected[None, first:first + 256]
            )

            contributions[band] += (
                np.exp(
                    kappa * (np.cos(difference) - 1.0)
                ).sum(axis=1)
                / denominator
            )

    density = contributions.sum(axis=0)
    mass = float(
        density.sum() * 2.0 * np.pi / grid_size
    )

    contributions /= mass
    density = contributions.sum(axis=0)

    # Preserve relative contributions and normalize display thickness.
    layers = contributions / density.max()

    return {
        "theta": np.r_[theta, 2.0 * np.pi],
        "layers": np.column_stack((
            layers,
            layers[:, 0],
        )),
        "density": density,
        "counts": np.bincount(
            indices,
            minlength=bands,
        ),
    }