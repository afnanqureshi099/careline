from flask import Flask
from sqlalchemy import inspect, text
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash
from config import Config


db = SQLAlchemy()


def upgrade_existing_schema():
    try:
        columns = {column["name"] for column in inspect(db.engine).get_columns("medicine_log")}
        if "snoozed_until" not in columns:
            db.session.execute(text("ALTER TABLE medicine_log ADD COLUMN snoozed_until DATETIME"))
        columns = {column["name"] for column in inspect(db.engine).get_columns("notification")}
        if "notification_key" not in columns:
            db.session.execute(text("ALTER TABLE notification ADD COLUMN notification_key VARCHAR(180)"))
        columns = {column["name"] for column in inspect(db.engine).get_columns("user")}
        if "role" not in columns:
            db.session.execute(text("ALTER TABLE user ADD COLUMN role VARCHAR(30) NOT NULL DEFAULT 'user'"))
        if "active" not in columns:
            db.session.execute(text("ALTER TABLE user ADD COLUMN active BOOLEAN NOT NULL DEFAULT 1"))
        columns = {column["name"] for column in inspect(db.engine).get_columns("user_settings")}
        for column_name, column_sql in {
            "reminder_enabled": "BOOLEAN DEFAULT 1",
            "reminder_sound": "VARCHAR(20) DEFAULT 'On'",
            "vibration": "BOOLEAN DEFAULT 1",
            "notification_timing_minutes": "INTEGER DEFAULT 10",
            "push_notifications": "BOOLEAN DEFAULT 1",
            "email_notifications": "BOOLEAN DEFAULT 1",
            "default_reminder_time": "VARCHAR(20) DEFAULT '08:00'",
            "snooze_duration": "INTEGER DEFAULT 10",
            "repeat_missed": "BOOLEAN DEFAULT 1",
            "time_zone": "VARCHAR(80) DEFAULT 'Asia/Kolkata'",
            "time_format": "VARCHAR(20) DEFAULT '12-hour'",
            "date_format": "VARCHAR(20) DEFAULT 'DD/MM/YYYY'",
            "theme": "VARCHAR(20) DEFAULT 'Light'",
            "language": "VARCHAR(20) DEFAULT 'English'",
            "caregiver_name": "VARCHAR(120) DEFAULT ''",
            "caregiver_contact": "VARCHAR(30) DEFAULT ''",
            "caregiver_access": "BOOLEAN DEFAULT 0",
        }.items():
            if column_name not in columns:
                db.session.execute(text(f"ALTER TABLE user_settings ADD COLUMN {column_name} {column_sql}"))
    except Exception:
        pass
    db.session.commit()


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if test_config:
        app.config.update(test_config)
    db.init_app(app)

    from . import models, routes
    app.register_blueprint(routes.bp)
    app.context_processor(lambda: {"current_user": routes.current_user})

    with app.app_context():
        db.create_all()
        upgrade_existing_schema()
        admin_email = app.config["ADMIN_EMAIL"].strip().lower()
        admin_user = models.User.query.filter_by(email=admin_email).first()
        migrated_legacy_admin = False
        if admin_user is None and admin_email != "admin@dailycare.local":
            admin_user = models.User.query.filter_by(email="admin@dailycare.local").first()
            if admin_user:
                admin_user.email = admin_email
            migrated_legacy_admin = True
        if admin_user is None:
            admin_user = models.User(
                full_name="Daily Care Admin",
                email=admin_email,
                phone="9876543210",
                password_hash=generate_password_hash(app.config["ADMIN_PASSWORD"]),
                role="admin",
            )
            db.session.add(admin_user)
            db.session.flush()
            db.session.add(models.PatientProfile(user_id=admin_user.id, age=30, gender="Admin"))
            db.session.add(models.UserSettings(user_id=admin_user.id))
            db.session.commit()
        elif migrated_legacy_admin:
            admin_user.password_hash = generate_password_hash(app.config["ADMIN_PASSWORD"])
            admin_user.role = "admin"
            admin_user.active = True
            db.session.commit()

    return app
