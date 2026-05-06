"""Module entry point: ``python -m bearings``.

Delegates to :func:`bearings.app.main`. The script entry point
defined in ``pyproject.toml`` (``bearings = "bearings.app:main"``)
calls into the same function, so ``python -m bearings`` and the
installed ``bearings`` shim share one code path.
"""

from bearings.app import main

if __name__ == "__main__":
    main()
