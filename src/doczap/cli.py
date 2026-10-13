from __future__ import annotations

import argparse
import logging
import sys

from doczap.conversion import convert_document


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="doczap",
        description="Fast, local, private DOCX to PDF conversion that keeps the layout intact.",
    )
    parser.add_argument("input_file", help="Path to input DOCX file.")
    parser.add_argument(
        "output_file",
        nargs="?",
        help="Optional output PDF path. Defaults to beside the input file.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Allow overwriting output file if it already exists.",
    )
    return parser


def configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")


def main() -> int:
    configure_logging()
    parser = build_parser()
    args = parser.parse_args()

    logging.info("Conversion started: input=%s", args.input_file)

    try:
        output_path = convert_document(
            args.input_file, args.output_file or None, overwrite=args.overwrite
        )
    except Exception as exc:
        logging.error("Conversion failed: %s", exc)
        return 1

    logging.info("Conversion succeeded: output=%s", output_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
