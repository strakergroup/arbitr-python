"""Single source of truth for the package version.

Hatch reads ``__version__`` from here via ``[tool.hatch.version]``, so the
distribution metadata and the ``User-Agent`` header can never disagree.
"""

__version__ = "0.1.0"
