"""Beat-snapping and bar-counting utilities."""

from __future__ import annotations

import bisect


def snap_to_downbeat(timestamp: float, downbeats: list[float]) -> float:
    """Snap a timestamp to the nearest downbeat position.

    Returns the original timestamp if downbeats is empty.
    """
    if not downbeats:
        return timestamp

    idx = bisect.bisect_left(downbeats, timestamp)

    candidates: list[float] = []
    if idx > 0:
        candidates.append(downbeats[idx - 1])
    if idx < len(downbeats):
        candidates.append(downbeats[idx])

    return min(candidates, key=lambda d: abs(d - timestamp))


def count_bars(start: float, end: float, downbeats: list[float]) -> int:
    """Count the number of bars in a time range [start, end).

    A bar is counted for each downbeat that falls within the range.
    Returns at least 1 if the segment spans any time.
    """
    if not downbeats:
        return 1 if end > start else 0

    lo = bisect.bisect_left(downbeats, start)
    hi = bisect.bisect_left(downbeats, end)
    count = hi - lo

    # Apply minimum-1 only when the segment is bracketed by known downbeats
    # (i.e., start is before the last downbeat, meaning the segment is within the song).
    if end > start and count == 0 and lo < len(downbeats):
        return 1
    return count
