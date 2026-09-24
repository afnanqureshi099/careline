import os
import time

from app import create_app
from app.reminders import run_reminder_cycle


def main():
    app = create_app()
    interval = max(15, int(os.getenv("REMINDER_INTERVAL_SECONDS", "60")))
    while True:
        run_reminder_cycle(app)
        time.sleep(interval)


if __name__ == "__main__":
    main()