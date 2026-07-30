from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

def configure_logging(verbose: bool) -> None:
    """At default INFO: show bridge events on ``__main__``; quiet aioice / aiohttp.access.

    Forwarded CrispASR stderr uses DEBUG unless ``relay_stderr(..., crisp_verbose=True)`` (see ``-v``).

    With ``verbose``, raise aioice-related loggers to DEBUG and HTTP access to INFO."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s:%(name)s:%(message)s",
        force=True,
    )

    if verbose:
        logging.getLogger("aiohttp.access").setLevel(logging.INFO)
        logging.getLogger("aiohttp.server").setLevel(logging.INFO)
        logging.getLogger("aioice").setLevel(logging.DEBUG)
        logging.getLogger("aiortc").setLevel(logging.INFO)
        logging.getLogger("av").setLevel(logging.INFO)
    else:
        logging.getLogger("aiohttp.access").setLevel(logging.WARNING)
        logging.getLogger("aiohttp.server").setLevel(logging.WARNING)
        logging.getLogger("aioice").setLevel(logging.WARNING)
        logging.getLogger("aiortc").setLevel(logging.WARNING)
        logging.getLogger("av").setLevel(logging.WARNING)

    logger.setLevel(logging.INFO)
