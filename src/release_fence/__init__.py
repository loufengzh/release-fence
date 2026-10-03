"""ZIP packaging quality gates. No extraction or execution."""
from .core import FenceError, Policy, scan, diff
__all__ = ["FenceError", "Policy", "scan", "diff"]
__version__ = "0.1.0"
