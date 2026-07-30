#!/usr/bin/env python3
"""WebRTC -> CrispASR bridge entry point."""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

from bridge_config import parse_args, run_config_from_ns
from bridge_logging import configure_logging
from bridge_runtime import async_main
from translation import load_merged_glossary, resolve_translation_system_prompt

logger = logging.getLogger(__name__)


def main() -> None:
    ns, crisp_extra = parse_args(sys.argv)
    configure_logging(ns.verbose)

    profile_name = Path(ns.bridge_config_path).name if getattr(ns, "bridge_config_path", None) else ""
    cfg = run_config_from_ns(ns, crisp_extra, profile_name=profile_name or "cli")
    if cfg.translate_enabled:
        cfg.glossary = load_merged_glossary((ns.glossary_file or "").strip() or None)
        cfg.system_prompt = resolve_translation_system_prompt(
            (ns.translate_prompt_file or "").strip() or None,
            cfg.glossary,
        )
        if (ns.translate_prompt_file or "").strip():
            logger.info("Translation prompt file: %s", (ns.translate_prompt_file or "").strip())
        if (ns.glossary_file or "").strip():
            logger.info("Glossary file: %s", (ns.glossary_file or "").strip())
    if getattr(ns, "bridge_config_path", None):
        logger.info("Bridge config: %s", ns.bridge_config_path)

    try:
        asyncio.run(async_main(cfg, ns.host, ns.port))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
