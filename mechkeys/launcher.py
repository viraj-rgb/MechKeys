"""Entry point. Kept import-light so a second launch can hand off to the running
instance in milliseconds, before numpy, Tk and the audio stack are loaded."""

from __future__ import annotations

import argparse

from . import winutil


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="MechKeys")
    parser.add_argument("--minimized", action="store_true", help="start hidden in the tray")
    args = parser.parse_args(argv)

    instance = winutil.SingleInstance()
    if not instance.is_primary:
        instance.notify_primary()
        return

    from .app import run  # heavy imports happen only in the first instance

    run(start_hidden=args.minimized, instance=instance)