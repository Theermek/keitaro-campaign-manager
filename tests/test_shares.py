import pytest

from app.services.shares import ShareError, ShareRow, rebalance


def shares(rows: list[ShareRow]) -> list[int]:
    return [r.share for r in rebalance(rows)]


@pytest.mark.parametrize(
    ("rows", "expected"),
    [
        # Video, 10.21 -> 16.30: third offer added to 50/50, remainder goes to the last one
        ([ShareRow(3749, 50), ShareRow(3717, 50), ShareRow(11111, 0)], [33, 33, 34]),
        # Video, 16.47: fourth offer
        ([ShareRow(1, 33), ShareRow(2, 33), ShareRow(3, 34), ShareRow(4, 0)], [25, 25, 25, 25]),
        # Remainder is spread +1 over the last offers, not dumped on one
        ([ShareRow(i, 0) for i in range(7)], [14, 14, 14, 14, 14, 15, 15]),
        ([ShareRow(i, 0) for i in range(6)], [16, 16, 17, 17, 17, 17]),
        ([ShareRow(1, 0)], [100]),
    ],
)
def test_even_split(rows, expected):
    assert shares(rows) == expected
    assert sum(expected) == 100


def test_removed_offers_get_zero_and_are_excluded():
    rows = [ShareRow(1, 25), ShareRow(2, 25, removed=True), ShareRow(3, 25), ShareRow(4, 25, removed=True)]
    assert shares(rows) == [50, 0, 50, 0]


def test_pinned_shares_are_kept():
    rows = [ShareRow(1, 40, pinned=True), ShareRow(2, 0), ShareRow(3, 0), ShareRow(4, 0)]
    assert shares(rows) == [40, 20, 20, 20]


def test_pinned_with_remainder():
    rows = [ShareRow(1, 25, pinned=True), ShareRow(2, 25), ShareRow(3, 25)]
    assert shares(rows) == [25, 37, 38]


def test_removed_pinned_offer_does_not_count():
    rows = [ShareRow(1, 60, pinned=True, removed=True), ShareRow(2, 0), ShareRow(3, 0)]
    assert shares(rows) == [0, 50, 50]


def test_all_pinned_left_as_is():
    rows = [ShareRow(1, 60, pinned=True), ShareRow(2, 30, pinned=True)]
    assert shares(rows) == [60, 30]


def test_order_and_flags_are_preserved():
    rows = [ShareRow(5, 0, pinned=False), ShareRow(1, 50, pinned=True), ShareRow(9, 0, removed=True)]
    result = rebalance(rows)
    assert [(r.offer_id, r.pinned, r.removed) for r in result] == [(5, False, False), (1, True, False), (9, False, True)]


def test_empty():
    assert rebalance([]) == []


def test_pinned_over_100_is_rejected():
    with pytest.raises(ShareError):
        rebalance([ShareRow(1, 70, pinned=True), ShareRow(2, 40, pinned=True)])
