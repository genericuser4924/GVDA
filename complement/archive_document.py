"""Recognize whitespace station documents without GUI dependencies."""
import math
import ntpath
import re
from datetime import datetime


def _number(value):
    try:
        return math.isfinite(float(value))
    except (ValueError, OverflowError):
        return False


def _epoch_candidate(value):
    if re.fullmatch(r"\d{8}", value):
        try:
            datetime.strptime(value, "%Y%m%d")
            return True
        except ValueError:
            pass

    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        try:
            datetime.strptime(value, "%Y-%m-%d")
            return True
        except ValueError:
            return False

    if _number(value):
        number = float(value)
        return 1800 <= number < 2500 or 10000 <= number < 100000

    return False


def recognize_station_document(member_path, content, cancelled=None):
    """Return a candidate document; scientific validation remains mandatory."""
    check = cancelled or (lambda: False)
    encoding = "unicode"

    if isinstance(content, bytes):
        try:
            content = content.decode("utf-8-sig")
            encoding = "utf-8-sig"
        except UnicodeDecodeError:
            content = content.decode("cp1252")
            encoding = "cp1252"

    if not isinstance(content, str) or "\x00" in content:
        raise ValueError("Unsupported text document.")

    lines = content.lstrip("\ufeff").splitlines()
    records = []

    for index, line in enumerate(lines):
        if check():
            raise InterruptedError("Document recognition cancelled.")

        text = line.strip()
        if text and not text.startswith(("#", "%", "!")):
            records.append((index, text.split()))

    start = None

    for offset in range(len(records) - 2):
        if check():
            raise InterruptedError("Document recognition cancelled.")

        sample = records[offset:offset + 3]
        width = len(sample[0][1])

        if width < 3 or any(
            len(fields) != width for _, fields in sample
        ):
            continue

        if any(
            sum(_number(v) for v in fields) < 3
            for _, fields in sample
        ):
            continue

        epochs = set(range(min(width, 4)))
        for _, fields in sample:
            epochs &= {
                i for i in epochs if _epoch_candidate(fields[i])
            }

        if epochs:
            start = offset
            break

    if start is None:
        raise ValueError(
            "No consistent time-series candidate block was found."
        )

    line_index, first_fields = records[start]
    width = len(first_fields)
    columns = None

    if start:
        header = records[start - 1][1]
        if (
            len(header) == width
            and not any(_number(v) for v in header)
        ):
            if len(set(header)) != width:
                raise ValueError("Ambiguous duplicate column labels.")
            columns = header

    origin = "explicit" if columns is not None else "generated"

    if columns is None:
        columns = [f"column_{i + 1}" for i in range(width)]

    rows, rejected = [], 0

    for _, fields in records[start:]:
        if check():
            raise InterruptedError("Document recognition cancelled.")

        if len(fields) == width:
            rows.append(" ".join(fields))
        else:
            rejected += 1

    return {
        "station_id": ntpath.splitext(
            ntpath.basename(member_path)
        )[0],
        "member_path": member_path,
        "source_lines": tuple([" ".join(columns)] + rows),
        "column_names": tuple(columns),
        "detected_format": "whitespace_table",
        "header_origin": origin,
        "first_data_line": line_index + 1,
        "inspection_rejected_row_count": rejected,
        "metadata": {
            "encoding": encoding,
            "preamble": tuple(lines[:line_index]),
        },
        "status": "unknown",
    }