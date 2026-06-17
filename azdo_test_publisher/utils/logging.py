from __future__ import annotations

import logging
import sys


def configure_logging(verbose: bool = False, debug: bool = False) -> None:
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(levelname)s %(message)s",
        stream=sys.stdout,
        force=True,
    )
