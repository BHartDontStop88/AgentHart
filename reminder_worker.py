import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

from dotenv import load_dotenv
load_dotenv(BASE_DIR / ".env")

from memory_factory import create_memory_store
from agents.notify import send_telegram


def main():
    """Run the reminder checker loop — fires Telegram alerts when reminders are due."""
    print("Reminder worker started. Press Ctrl+C to stop.")

    try:
        while True:
            memory = create_memory_store(BASE_DIR)
            due_reminders = memory.due_reminders()

            for index, reminder in due_reminders:
                msg = f"Reminder: {reminder['text']}"
                print(msg)
                send_telegram(msg)
                memory.complete_reminder(index)

            time.sleep(60)
    except KeyboardInterrupt:
        print("\nReminder worker stopped.")


if __name__ == "__main__":
    main()
