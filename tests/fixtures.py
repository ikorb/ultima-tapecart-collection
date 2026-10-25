"""The RAM fixtures in tests/data, captured in VICE from the cart the disks
build (tools/vice/fixtures.py, `make fixtures`) and never shipped: the tests
that need one skip without it."""
import os
import unittest

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


def path(name):
    return os.path.join(DATA, name)


def needs(*names):
    """skipIf for a test (or class) that reads these fixtures."""
    gone = [n for n in names if not os.path.exists(path(n))]
    return unittest.skipIf(bool(gone), f"no tests/data/{', '.join(gone)} (make fixtures)")
