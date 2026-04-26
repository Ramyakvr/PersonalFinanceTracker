"""Tests for the Decimal XIRR solver.

Golden values cross-checked against Microsoft Excel's XIRR. Tolerances are
loose at the 5th decimal (1e-5) which is tighter than anything a user would
read off a portfolio page.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from core.services.xirr import xirr

TOL = Decimal("1e-5")


def _close(a: Decimal, b: Decimal, tol: Decimal = TOL) -> bool:
    return abs(a - b) < tol


def test_excel_documented_example() -> None:
    """Microsoft Excel XIRR help page example.

    XIRR({-10000, 2750, 4250, 3250, 2750},
         {2008-01-01, 2008-03-01, 2008-10-30, 2009-02-15, 2009-04-01})
    = 0.373362535
    """
    flows = [
        (date(2008, 1, 1), Decimal("-10000")),
        (date(2008, 3, 1), Decimal("2750")),
        (date(2008, 10, 30), Decimal("4250")),
        (date(2009, 2, 15), Decimal("3250")),
        (date(2009, 4, 1), Decimal("2750")),
    ]
    result = xirr(flows)
    assert result is not None
    assert _close(result, Decimal("0.37336253")), f"got {result}"


def test_doubles_in_one_year_is_100pct() -> None:
    flows = [
        (date(2020, 1, 1), Decimal("-100")),
        (date(2021, 1, 1), Decimal("200")),
    ]
    result = xirr(flows)
    assert result is not None
    # 2020 is a leap year -> 366 days under Actual/365 => 2^(365/366) - 1 ≈ 0.99622.
    assert _close(result, Decimal("0.99622"), Decimal("1e-4"))


def test_half_loss_in_one_year() -> None:
    flows = [
        (date(2021, 1, 1), Decimal("-100")),  # non-leap year for clean math
        (date(2022, 1, 1), Decimal("50")),
    ]
    result = xirr(flows)
    assert result is not None
    # 365 days exactly: 50/100 = (1+r)^1 → r = -0.5
    assert _close(result, Decimal("-0.5"))


def test_dca_then_exit() -> None:
    """Dollar-cost-average: buy 10,000 on the 1st of each month, sell all at +1yr for 130,000."""
    buys = [(date(2023, m, 1), Decimal("-10000")) for m in range(1, 13)]
    buys.append((date(2024, 1, 1), Decimal("130000")))
    result = xirr(buys)
    assert result is not None
    # 120,000 invested on a declining schedule, exits at 130,000. Weighted avg
    # holding is ~6.5 months so the XIRR on a ~8.3% absolute gain lands near 15.7%.
    assert _close(result, Decimal("0.15670"), Decimal("1e-4"))


def test_buy_plus_dividend_plus_exit() -> None:
    """Portfolio XIRR shape: a buy, a dividend halfway, an exit."""
    flows = [
        (date(2022, 1, 1), Decimal("-10000")),
        (date(2022, 7, 1), Decimal("200")),  # dividend
        (date(2023, 1, 1), Decimal("11000")),  # sell at a +10% gain plus dividend
    ]
    result = xirr(flows)
    assert result is not None
    # NPV solves to r ≈ 0.12119 (10% price gain + 2% yield, annualised with dividend timing).
    assert _close(result, Decimal("0.12119"), Decimal("1e-4"))


# ---------------------------------------------------------------------------
# Guard cases -- solver returns None (not a wrong number, not an exception)
# ---------------------------------------------------------------------------


def test_single_flow_returns_none() -> None:
    assert xirr([(date(2024, 1, 1), Decimal("100"))]) is None


def test_all_positive_returns_none() -> None:
    flows = [
        (date(2024, 1, 1), Decimal("100")),
        (date(2024, 6, 1), Decimal("50")),
    ]
    assert xirr(flows) is None


def test_all_negative_returns_none() -> None:
    flows = [
        (date(2024, 1, 1), Decimal("-100")),
        (date(2024, 6, 1), Decimal("-50")),
    ]
    assert xirr(flows) is None


def test_same_date_returns_none() -> None:
    flows = [
        (date(2024, 1, 1), Decimal("-100")),
        (date(2024, 1, 1), Decimal("150")),
    ]
    assert xirr(flows) is None


def test_zero_flows_are_stripped() -> None:
    """Zero flows in the input should not prevent a valid XIRR from converging."""
    flows = [
        (date(2022, 1, 1), Decimal("-100")),
        (date(2022, 6, 1), Decimal("0")),  # noise
        (date(2023, 1, 1), Decimal("110")),
    ]
    result = xirr(flows)
    assert result is not None
    assert result > Decimal("0.09") and result < Decimal("0.11")


def test_empty_flows_returns_none() -> None:
    assert xirr([]) is None


def test_only_zero_flows_returns_none() -> None:
    flows = [
        (date(2024, 1, 1), Decimal("0")),
        (date(2024, 6, 1), Decimal("0")),
    ]
    assert xirr(flows) is None


# ---------------------------------------------------------------------------
# Robustness
# ---------------------------------------------------------------------------


def test_bad_guess_still_converges() -> None:
    """A wildly wrong guess should fall back to bisection and still find the root."""
    flows = [
        (date(2020, 1, 1), Decimal("-1000")),
        (date(2023, 1, 1), Decimal("2000")),
    ]
    # 3 years spanning 2020 (leap): 1096 days => 2^(365/1096) - 1 ≈ 0.25966.
    result = xirr(flows, guess=Decimal("10"))
    assert result is not None
    assert _close(result, Decimal("0.25966"), Decimal("1e-3"))


def test_near_total_loss_returns_none() -> None:
    """A 10,000 -> 1 loss yields an XIRR of ~-0.9999, below our -0.99 bracket floor.

    This is documented behaviour: XIRR returns None when the root falls outside
    ``[-0.99, 100]``. Callers render a dash and surface the realised loss
    directly rather than a wildly negative percentage.
    """
    flows = [
        (date(2020, 1, 1), Decimal("-10000")),
        (date(2021, 1, 1), Decimal("1")),
    ]
    assert xirr(flows) is None


@pytest.mark.parametrize(
    "flows",
    [
        [  # single date cluster
            (date(2024, 3, 1), Decimal("-100")),
            (date(2024, 3, 1), Decimal("50")),
            (date(2024, 3, 1), Decimal("75")),
        ],
    ],
)
def test_degenerate_clusters_return_none(flows: list[tuple[date, Decimal]]) -> None:
    assert xirr(flows) is None
