"""Entry point for the plugin hooks: put this directory on sys.path and dispatch."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))

if __name__ == "__main__":
    try:
        from quests.hooks import main

        code = main(sys.argv[1:])
    except Exception:  # a hook must never fail a session
        code = 0
        try:
            import traceback

            d = os.environ.get("QUESTS_STATE_DIR") or os.path.join(
                os.path.expanduser("~"), ".claude", "state", "quests")
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, "hook-errors.log"), "a", encoding="utf-8") as fh:
                fh.write("quests_hooks entry\n" + traceback.format_exc() + "\n")
        except Exception:
            pass
    sys.exit(code)
