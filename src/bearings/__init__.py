"""bearings — universal Python project boilerplate.

Forks rename the package and replace this docstring with their own.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("bearings")
except PackageNotFoundError:  # pragma: no cover - happens only pre-install
    __version__ = "0.0.0+unknown"

__all__ = ["__version__"]
