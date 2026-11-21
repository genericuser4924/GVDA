import math
import numpy as np

"""
def circular_scores_compatible(angles, progress=None):
    #Preserve the original score calculation for finite azimuths.
    ordered = sorted(angles)
    count = len(ordered)

    if count == 0:
        return ordered, {}

    radians = [
        angle * math.pi / 180
        for angle in ordered
    ]

    scores = {}
    last_progress = -1

    for index, angle in enumerate(ordered):
        if angle not in scores:
            candidate = radians[index]
            total = 0

            for observed in radians:
                total += abs(
                    math.pi
                    - abs(observed - candidate)
                )

            scores[angle] = (
                math.pi - total / count
            )

        if progress is not None:
            percent = int(
                100 * (index + 1) / count
            )

            if percent != last_progress:
                progress(percent)
                last_progress = percent

    return ordered, scores

"""

def circular_scores_compatible(angles, progress=None):
    """Calculate circular scores with sequential accumulation."""
    ordered = sorted(angles)
    count = len(ordered)

    if count == 0:
        return ordered, {}

    radians = np.asarray(
        [angle * math.pi / 180 for angle in ordered],
        dtype=np.float64,
    )
    work = np.empty_like(radians)
    scores = {}
    last_progress = -1

    for index, angle in enumerate(ordered):
        if angle not in scores:
            candidate = radians[index]

            # Preserve the original operations and accumulation order.
            np.subtract(radians, candidate, out=work)
            np.abs(work, out=work)
            np.subtract(math.pi, work, out=work)
            np.abs(work, out=work)
            np.add.accumulate(work, out=work)

            total = float(work[-1])
            scores[angle] = math.pi - total / count

        if progress is not None:
            percent = int(100 * (index + 1) / count)

            if percent != last_progress:
                progress(percent)
                last_progress = percent

    return ordered, scores