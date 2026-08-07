"""Root logging configuration, driven by LOGGING_LEVEL."""

from __future__ import annotations

import logging
import sys


def configure_logging(level: str) -> None:
    resolved = getattr(logging, level.upper(), logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s")
    )
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(resolved)
    # discord.py's own gateway chatter is noisy at DEBUG and rarely useful.
    logging.getLogger("discord").setLevel(max(resolved, logging.WARNING))
