"""Which Þing this is."""

import importlib.metadata
import os


def ting_version() -> str:
    """The release the image was built as (or, built from a checkout, what git calls
    that commit); without either, the package's version marked as a development build."""
    built = os.environ.get("TING_VERSION", "").strip()
    return built or f"{importlib.metadata.version('ting-backend')}-dev"
