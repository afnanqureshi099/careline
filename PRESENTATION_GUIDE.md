# Presentation Guide

## Demo flow

1. Start with `py run.py` and open `http://127.0.0.1:5000`.
2. Register a user with a strong password such as `Demo@1234`.
3. Open **Settings** and set a personal water target, for example `2500 ml`.
4. Add a medicine:
   - Name: `Demo Medicine`
   - Dosage: `1 tablet`
   - Quantity: `5`
   - Low-stock threshold: `2`
   - Start date: today
5. Add a schedule at a time earlier than the current time. Choose `Daily`.
6. Open the dashboard. Explain that the system creates an occurrence and marks it `Missed` when it passes without a response.
7. Use **Taken**, **Skipped**, or **Remind Later**. Show the medicine history and notification center.
8. Add water, an activity, and a health record. Show the weekly reports page.
9. Edit the medicine, then demonstrate search and schedule removal.

## Explain clearly

- The system stores user-entered prescription information and reminders only.
- It does not diagnose conditions, recommend medicines, recommend dosages, or alter prescriptions.
- Every business record is linked to the authenticated user.
- Passwords are hashed; the default development database is SQLite and MySQL is supported with `DATABASE_URL`.

## Important limitation to disclose

Browser push notifications and a background worker are not enabled in this academic demo. Reminder occurrences and in-app notifications are generated when an authenticated dashboard or notification page is opened. A production version should run this generation in a scheduled worker and add CSRF protection, HTTPS, migrations, and a production WSGI server.
