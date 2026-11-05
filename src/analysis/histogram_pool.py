"""
Pools occupied latency buckets across repetitions and reads percentiles and
means from them. Buckets are (representative_ns, count) pairs emitted by the
harness; representatives are exact below 64 ns and bucket midpoints above.
"""

import math
from collections import Counter
from typing import Iterable, List, Sequence, Tuple

Bucket = Tuple[int, int]


def pool_buckets(bucket_lists: Iterable[Sequence[Sequence[int]]]) -> List[Bucket]:
    """Sums counts per representative value across repetitions."""
    totals: Counter = Counter()
    for buckets in bucket_lists:
        for value, count in buckets:
            totals[int(value)] += int(count)
    return sorted(totals.items())


def total_count(buckets: Sequence[Bucket]) -> int:
    return sum(count for _, count in buckets)


def weighted_percentile(buckets: Sequence[Bucket], percent: float) -> int:
    """Smallest representative whose cumulative count reaches the rank."""
    total = total_count(buckets)
    if total == 0:
        return 0
    if percent >= 100.0:
        return buckets[-1][0]
    target = max(1, math.ceil(percent / 100.0 * total))
    cumulative = 0
    for value, count in buckets:
        cumulative += count
        if cumulative >= target:
            return value
    return buckets[-1][0]


def weighted_mean(buckets: Sequence[Bucket]) -> float:
    total = total_count(buckets)
    if total == 0:
        return float("nan")
    return sum(value * count for value, count in buckets) / total
