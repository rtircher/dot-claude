"""Entry point for bin/quest: put this directory on sys.path and run the CLI."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))

from quests.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
