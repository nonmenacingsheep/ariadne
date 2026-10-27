import logging
import signal
import sys

from gi.repository import GLib

from .layer import DeskApp


def main() -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s desk %(levelname)s %(name)s: %(message)s")
    app = DeskApp()
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, app.quit)
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, app.quit)
    return app.run([])


if __name__ == "__main__":
    sys.exit(main())
