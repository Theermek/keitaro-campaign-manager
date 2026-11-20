"""Offer share distribution, as in the existing editor.

- shares are integers; active offers sum up to 100;
- pinned shares are kept, the rest (100 - pinned) is split evenly between
  active unpinned offers;
- the remainder goes +1 to the last offers (Keitaro order), so the
  difference between offers is at most 1: 3 offers -> 33/33/34;
- removed offers get 0.
"""

from dataclasses import dataclass, replace

TOTAL = 100


@dataclass(frozen=True)
class ShareRow:
    offer_id: int
    share: int
    pinned: bool = False
    removed: bool = False


class ShareError(ValueError):
    pass


def rebalance(rows: list[ShareRow]) -> list[ShareRow]:
    """Returns rows in the same order with recalculated shares."""
    active = [r for r in rows if not r.removed]
    pinned_total = sum(r.share for r in active if r.pinned)
    if any(r.share < 0 for r in active if r.pinned):
        raise ShareError("Pinned shares cannot be negative")
    if pinned_total > TOTAL:
        raise ShareError(f"Pinned shares sum to {pinned_total}%, more than {TOTAL}%")

    free_ids = [r.offer_id for r in active if not r.pinned]
    shares: dict[int, int] = {}
    if free_ids:
        base, remainder = divmod(TOTAL - pinned_total, len(free_ids))
        bumped = set(free_ids[len(free_ids) - remainder:]) if remainder else set()
        shares = {oid: base + (1 if oid in bumped else 0) for oid in free_ids}

    result = []
    for r in rows:
        if r.removed:
            result.append(replace(r, share=0))
        elif r.offer_id in shares:
            result.append(replace(r, share=shares[r.offer_id]))
        else:
            result.append(r)
    return result
