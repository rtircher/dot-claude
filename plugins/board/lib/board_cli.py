"""Entry point for bin/board: put this directory on sys.path and run the CLI."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))

from board.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
