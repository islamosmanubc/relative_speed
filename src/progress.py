from __future__ import annotations

from typing import Iterable, Iterator, TypeVar

T = TypeVar("T")


def progress_iter(items: Iterable[T], total: int, desc: str) -> Iterator[T]:
    try:
        from tqdm import tqdm  # type: ignore
    except ImportError:
        tqdm = None

    if tqdm is not None:
        return iter(tqdm(items, total=total, desc=desc, unit="frame"))

    return _fallback_progress(items, total, desc)


def _fallback_progress(items: Iterable[T], total: int, desc: str) -> Iterator[T]:
    step = max(1, total // 50) if total > 0 else 1
    count = 0
    for item in items:
        count += 1
        if count == 1 or count == total or (count % step == 0):
            if total > 0:
                pct = 100.0 * count / total
                print(f"{desc}: {count}/{total} ({pct:.1f}%)")
            else:
                print(f"{desc}: {count}")
        yield item
