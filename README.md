# Personalized Medicine & Daily Care Reminder System

A patient-focused reminder and record-management application built with Flask, HTML, CSS, JavaScript, and SQLAlchemy. It stores user-entered prescriptions and health records only. It does not diagnose, recommend medicines or dosages, or change prescriptions.

## Run locally

1. Install Python 3.11+ and MySQL 8 if you want a MySQL database.
2. Create a virtual environment:
   - Windows: `py -m venv .venv` then `.venv\\Scripts\\activate`
3. Install packages: `pip install -r requirements.txt`
4. Optional MySQL setup:
   - `CREATE DATABASE care_reminders CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;`
   - PowerShell: `$env:DATABASE_URL = 'mysql+pymysql://user:password@localhost/care_reminders'`
   - Without this variable, the app uses local `care.db` SQLite for easy development.
5. Start the app: `python run.py`
6. Open http://127.0.0.1:5000

Change `SECRET_KEY` in any non-local deployment. The schema is also available in `schema.sql` for MySQL review or manual setup.

## Deploy on Render

Push this repository to GitHub, create a Render Web Service from it, and use `pip install -r requirements.txt` as the build command and `gunicorn run:app` as the start command. Set `SECRET_KEY` to a generated secret and set `DATABASE_URL` to a hosted MySQL connection string such as `mysql+pymysql://user:password@host/database`. The included `render.yaml` can prefill the service settings.

## Scope

The application records information entered by the user. Reminder labels are informational and users should follow their healthcare professional's instructions.
