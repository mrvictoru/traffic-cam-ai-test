"""Command line entry points for the traffic camera pipeline."""

from __future__ import annotations

import argparse


def build_parser() -> argparse.ArgumentParser:
    """Create a CLI parser with the core subcommands."""
    parser = argparse.ArgumentParser(description="Traffic cam ingestion and analysis pipeline")
    parser.add_argument("--mode", choices=["discover", "capture", "analyze"], default="discover")
    parser.add_argument("--output-dir", default="output")
    return parser


def main() -> int:
    """CLI entry point."""
    parser = build_parser()
    args = parser.parse_args()
    print(f"Mode: {args.mode}; output-dir: {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
