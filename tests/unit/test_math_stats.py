"""Tests for MathStatsTool — arithmetic, single-number, and statistics ops."""
from __future__ import annotations

import pytest

from agentic_workflows.tools.math_stats import MathStatsTool

tool = MathStatsTool()


def execute(op, **kwargs):
    return tool.execute({"operation": op, **kwargs})


# ---------------------------------------------------------------------------
# Unknown operation
# ---------------------------------------------------------------------------

def test_unknown_operation():
    r = execute("explode")
    assert "error" in r
    assert "supported_operations" in r


# ---------------------------------------------------------------------------
# Two-number arithmetic
# ---------------------------------------------------------------------------

def test_add():
    assert execute("add", a=3, b=4)["result"] == 7


def test_add_floats():
    assert execute("add", a=1.5, b=2.5)["result"] == pytest.approx(4.0)


def test_subtract():
    assert execute("subtract", a=10, b=3)["result"] == 7


def test_multiply():
    assert execute("multiply", a=6, b=7)["result"] == 42


def test_divide():
    assert execute("divide", a=10, b=4)["result"] == pytest.approx(2.5)


def test_divide_by_zero():
    r = execute("divide", a=5, b=0)
    assert "error" in r


def test_power():
    assert execute("power", a=2, b=10)["result"] == 1024


def test_arithmetic_missing_args():
    r = execute("add", a=1)
    assert "error" in r


def test_arithmetic_non_numeric():
    r = execute("add", a="x", b=1)
    assert "error" in r


# ---------------------------------------------------------------------------
# Single-number ops
# ---------------------------------------------------------------------------

def test_sqrt():
    assert execute("sqrt", a=9)["result"] == pytest.approx(3.0)


def test_sqrt_negative():
    r = execute("sqrt", a=-1)
    assert "error" in r


def test_abs_positive():
    assert execute("abs", a=5)["result"] == 5


def test_abs_negative():
    assert execute("abs", a=-7)["result"] == 7


def test_single_missing_a():
    r = execute("sqrt")
    assert "error" in r


# ---------------------------------------------------------------------------
# List / statistics ops
# ---------------------------------------------------------------------------

def test_sum():
    assert execute("sum", numbers=[1, 2, 3, 4])["result"] == 10


def test_min():
    assert execute("min", numbers=[5, 3, 8, 1])["result"] == 1


def test_max():
    assert execute("max", numbers=[5, 3, 8, 1])["result"] == 8


def test_mean():
    assert execute("mean", numbers=[1, 2, 3, 4, 5])["result"] == pytest.approx(3.0)


def test_median_odd():
    assert execute("median", numbers=[1, 3, 5])["result"] == pytest.approx(3.0)


def test_median_even():
    assert execute("median", numbers=[1, 2, 3, 4])["result"] == pytest.approx(2.5)


def test_mode():
    assert execute("mode", numbers=[1, 2, 2, 3])["result"] == 2


def test_stdev():
    r = execute("stdev", numbers=[2, 4, 4, 4, 5, 5, 7, 9])
    assert "result" in r
    assert r["result"] == pytest.approx(2.138, rel=0.01)


def test_stdev_single_value():
    r = execute("stdev", numbers=[5])
    assert "error" in r


def test_variance():
    r = execute("variance", numbers=[2, 4, 6])
    assert "result" in r


def test_variance_single_value():
    r = execute("variance", numbers=[5])
    assert "error" in r


def test_list_empty():
    r = execute("sum", numbers=[])
    assert "error" in r


def test_list_non_numeric():
    r = execute("mean", numbers=[1, "x", 3])
    assert "error" in r


def test_list_not_a_list():
    r = execute("mean", numbers="1,2,3")
    assert "error" in r
