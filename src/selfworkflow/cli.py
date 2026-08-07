"""Command-line entry point for SelfWorkFlow."""

import argparse

from selfworkflow import __version__


def main() -> int:
    parser = argparse.ArgumentParser(prog="selfworkflow")
    parser.add_argument("--version", action="version", version=__version__)
    parser.parse_args()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
