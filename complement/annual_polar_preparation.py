"""Prepare annual absolute polar summaries using numerical data only."""

import math
from datetime import date


def _absolute_azimuth(north, east):
    """Preserve the quadrant and zero-vector rules used by dist_Az."""
    if north == 0:
        return 90.0 if east > 0 else 270.0 if east < 0 else 0.0
    if east == 0:
        return 0.0 if north >= 0 else 180.0
    angle = math.atan(east / north) * 180.0 / math.pi
    if north > 0 and east > 0:
        return angle
    if north < 0:
        return 180.0 + angle
    return 360.0 + angle


def _circular_summary(azimuths):
    """Use the complement's mean direction and circular SD formulas."""
    cosine_sum = sine_sum = 0.0
    for angle in azimuths:
        radians = angle * math.pi / 180.0
        cosine_sum += math.cos(radians)
        sine_sum += math.sin(radians)
    resultant = min(1.0, math.sqrt(cosine_sum ** 2 + sine_sum ** 2) / len(azimuths))
    if resultant <= 1e-12:
        return None, None, resultant
    mean = _absolute_azimuth(cosine_sum, sine_sum)
    variance = 1.0 - resultant
    deviation = (180.0 / math.pi) * math.sqrt(-2.0 * math.log(1.0 - variance))
    return mean, deviation, resultant


def prepare_annual_polar(epochs, iso_dates, north, east, cancelled=None):
    """Return ten calendar slots without interpolation or GUI access."""
    cancelled = cancelled or (lambda: False)
    if cancelled():
        return None
    count = len(epochs)
    if not count or not (count == len(iso_dates) == len(north) == len(east)):
        raise ValueError("Epochs, ISO dates and component observations are not aligned.")
    groups = {}
    previous = None
    for index, (epoch, label, n, e) in enumerate(zip(epochs, iso_dates, north, east)):
        if index % 128 == 0 and cancelled():
            return None
        epoch = float(epoch)
        if not math.isfinite(epoch) or (previous is not None and epoch <= previous):
            raise ValueError("Annual plot epochs must be finite and strictly increasing.")
        previous = epoch
        label = str(label)
        year = date.fromisoformat(label).year
        n, e = float(n), float(e)
        if math.isfinite(n) and math.isfinite(e):
            groups.setdefault(year, []).append((epoch, label, n, e))
    if not groups:
        raise ValueError("No finite coordinate observations are available.")
    last_year = max(groups)
    first_year = last_year - 9
    if first_year < 1:
        raise ValueError("The ten-year window exceeds the supported calendar range.")
    rows = []
    for slot, year in enumerate(range(first_year, last_year + 1)):
        if cancelled():
            return None
        records = groups.get(year, [])
        row = dict(year=year, slot=slot, count=len(records), start=None, end=None,
                   distance=None, mean=None, deviation=None, resultant=None,
                   status="No data", inner=None, outer=None, thickness=0.0)
        if records:
            row["start"], row["end"] = records[0][1], records[-1][1]
        if len(records) >= 2:
            n0, e0 = records[0][2:]
            dn, de = records[-1][2] - n0, records[-1][3] - e0
            row["distance"] = math.sqrt(dn * dn + de * de)
            angles = []
            for index, record in enumerate(records[1:]):
                if index % 128 == 0 and cancelled():
                    return None
                angles.append(_absolute_azimuth(record[2] - n0, record[3] - e0))
            mean, deviation, resultant = _circular_summary(angles)
            row.update(mean=mean, deviation=deviation, resultant=resultant,
                       status="Valid" if mean is not None else "Undefined mean direction")
            if row["distance"] == 0.0:
                row["status"] = "Zero net displacement"
        elif records:
            row["status"] = "Insufficient observations"
        rows.append(row)
    maximum = max((row["distance"] or 0.0 for row in rows), default=0.0)
    band_width = 0.80 / 10.0
    for row in rows:
        center = 0.20 + (row["slot"] + 0.5) * band_width
        thickness = (0.90 * band_width * row["distance"] / maximum
                     if maximum > 0.0 and row["distance"] is not None else 0.0)
        row.update(center=center, thickness=thickness,
                   inner=center - thickness / 2.0, outer=center + thickness / 2.0)
    return dict(first_year=first_year, last_year=last_year, rows=tuple(rows),
                max_distance=maximum, band_width=band_width,
                max_thickness=0.90 * band_width)
