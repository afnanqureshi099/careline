from datetime import datetime
from . import db


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False)
    phone = db.Column(db.String(30))
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    profile = db.relationship("PatientProfile", backref="user", uselist=False, cascade="all, delete-orphan")
    settings = db.relationship("UserSettings", backref="user", uselist=False, cascade="all, delete-orphan")


class UserSettings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), unique=True, nullable=False)
    water_target_ml = db.Column(db.Integer, default=2000, nullable=False)
    water_reminder_times = db.Column(db.String(255), default="")


class PatientProfile(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), unique=True, nullable=False)
    age = db.Column(db.Integer)
    gender = db.Column(db.String(40))
    emergency_contact = db.Column(db.String(120))
    caregiver_info = db.Column(db.Text)


class Medicine(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    dosage = db.Column(db.String(120), nullable=False)
    quantity = db.Column(db.Float, default=0)
    low_stock_threshold = db.Column(db.Float, default=0)
    start_date = db.Column(db.Date)
    end_date = db.Column(db.Date)
    instructions = db.Column(db.String(255))
    notes = db.Column(db.Text)
    schedules = db.relationship("MedicineSchedule", backref="medicine", cascade="all, delete-orphan")


class MedicineSchedule(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    medicine_id = db.Column(db.Integer, db.ForeignKey("medicine.id", ondelete="CASCADE"), nullable=False)
    time = db.Column(db.Time, nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date)
    frequency = db.Column(db.String(30), nullable=False, default="Daily")
    logs = db.relationship("MedicineLog", backref="schedule", cascade="all, delete-orphan")


class MedicineLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    schedule_id = db.Column(db.Integer, db.ForeignKey("medicine_schedule.id", ondelete="CASCADE"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    event_date = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(20), nullable=False)
    snoozed_until = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class WaterLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    amount_ml = db.Column(db.Integer, nullable=False)
    logged_at = db.Column(db.DateTime, default=datetime.utcnow)


class DailyActivity(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    time = db.Column(db.Time)
    activity_date = db.Column(db.Date, nullable=False)
    frequency = db.Column(db.String(30), default="Once")
    logs = db.relationship("ActivityLog", backref="activity", cascade="all, delete-orphan")


class ActivityLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    activity_id = db.Column(db.Integer, db.ForeignKey("daily_activity.id", ondelete="CASCADE"), nullable=False)
    status = db.Column(db.String(20), default="Pending")
    logged_at = db.Column(db.DateTime, default=datetime.utcnow)


class HealthRecord(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    metric = db.Column(db.String(40), nullable=False)
    value = db.Column(db.String(80), nullable=False)
    recorded_at = db.Column(db.DateTime, default=datetime.utcnow)
    notes = db.Column(db.Text)


class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    title = db.Column(db.String(160), nullable=False)
    message = db.Column(db.Text, nullable=False)
    notification_key = db.Column(db.String(180), nullable=True)
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
