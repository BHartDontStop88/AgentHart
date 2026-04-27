import time
from pathlib import Path

from memory_factory import create_memory_store


def main():
    """Run a simple reminder checker until the user presses Ctrl+C."""
    base_dir = Path(__file__).resolve().parent
    print("Reminder worker started. Press Ctrl+C to stop.")

    try:
        while True:
            # Reload memory each loop so reminders added in main.py are noticed.
            memory = create_memory_store(base_dir)
            due_reminders = memory.due_reminders()

            for index, reminder in due_reminders:
                print(f"REMINDER: {reminder['text']}")
                memory.complete_reminder(index)

            # This worker is intentionally simple: check once every 60 seconds.
            time.sleep(60)
    except KeyboardInterrupt:
        print("\nReminder worker stopped.")


if __name__ == "__main__":
    main()
