import csv
import io
import re
import secrets
from datetime import date, datetime, time, timedelta
from functools import wraps
from flask import Blueprint, Response, flash, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash
from . import db
from .models import (ActivityLog, DailyActivity, HealthRecord, Medicine, MedicineLog,
                     CaregiverAccess, MedicineSchedule, Notification, PatientProfile, User, UserSettings, WaterLog)

bp = Blueprint("main", __name__)


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("main.login"))
        user = current_user()
        if not user or not user.active:
            session.clear()
            flash("Your account is inactive. Contact an administrator.", "error")
            return redirect(url_for("main.login"))
        return view(*args, **kwargs)
    return wrapped


def current_user():
    return db.session.get(User, session.get("user_id"))


def valid_password(value):
    return (len(value) >= 8 and re.search(r"[A-Z]", value) and re.search(r"[a-z]", value)
            and re.search(r"\d", value) and re.search(r"[^A-Za-z0-9]", value))


def normalize_phone(value):
    digits = re.sub(r"\D", "", (value or ""))
    return digits if len(digits) == 10 else None


def integer_value(value, minimum=0):
    try:
        number = float(value)
        if number.is_integer() and number >= minimum:
            return int(number)
    except (TypeError, ValueError):
        pass
    return None


def parse_date(value):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date() if value else None
    except ValueError:
        return None


def parse_time(value):
    try:
        return datetime.strptime(value, "%H:%M").time() if value else None
    except ValueError:
        return None


def positive_number(value, default=0):
    try:
        number = float(value)
        return number if number >= 0 else default
    except (TypeError, ValueError):
        return default


def schedule_runs_today(item, target):
    if item.start_date > target or (item.end_date and item.end_date < target):
        return False
    if item.frequency == "Once":
        return item.start_date == target
    if item.frequency == "Weekly":
        return item.start_date.weekday() == target.weekday()
    return True


def create_notification(user_id, key, title, message):
    if not Notification.query.filter_by(user_id=user_id, notification_key=key).first():
        db.session.add(Notification(user_id=user_id, notification_key=key, title=title, message=message))


def prepare_reminders(user_id, target=None, now=None):
    target = target or date.today()
    now = now or datetime.now()
    settings = UserSettings.query.filter_by(user_id=user_id).first()
    if settings and not settings.reminder_enabled:
        return {log.schedule_id: log for log in MedicineLog.query.filter_by(user_id=user_id, event_date=target).all()}
    timing = max(0, settings.notification_timing_minutes if settings else 10)
    schedules = MedicineSchedule.query.join(Medicine).filter(Medicine.user_id == user_id).all()
    logs = {log.schedule_id: log for log in MedicineLog.query.filter_by(user_id=user_id, event_date=target).all()}
    for item in schedules:
        if not schedule_runs_today(item, target):
            continue
        log = logs.get(item.id)
        if not log:
            log = MedicineLog(schedule_id=item.id, user_id=user_id, event_date=target, status="Upcoming")
            db.session.add(log)
            logs[item.id] = log
        reminder_time = datetime.combine(target, item.time) if item.time else None
        minutes_until = (reminder_time - now).total_seconds() / 60 if reminder_time else None
        if item.time and item.time <= now.time() and log.status == "Upcoming":
            log.status = "Missed"
            if not settings or settings.repeat_missed:
                create_notification(user_id, f"missed-{item.id}-{target}", "Missed medicine reminder", f"{item.medicine.name} was not marked at {item.time.strftime('%I:%M %p')}.")
        elif item.time and 0 <= minutes_until <= timing and log.status == "Upcoming":
            create_notification(user_id, f"due-{item.id}-{target}", "Medicine due", f"It is time to take {item.medicine.name} at {item.time.strftime('%I:%M %p')}.")
        elif log.status == "Remind Later" and log.snoozed_until and log.snoozed_until <= now:
            log.status = "Upcoming"
            create_notification(user_id, f"snooze-{item.id}-{target}-{log.snoozed_until.isoformat()}", "Snoozed medicine reminder", f"Reminder: take {item.medicine.name} now.")
        if item.medicine.quantity <= item.medicine.low_stock_threshold:
            create_notification(user_id, f"stock-{item.medicine.id}-{target}", "Low medicine quantity", f"{item.medicine.name} has {item.medicine.quantity} units remaining.")
        if item.end_date and item.end_date == target + timedelta(days=2):
            create_notification(user_id, f"ending-{item.medicine.id}-{target}", "Medicine schedule ending soon", f"Your {item.medicine.name} schedule will end in 2 days.")
    db.session.commit()
    return logs


@bp.route("/")
def index():
    return redirect(url_for("main.dashboard" if "user_id" in session else "main.login"))


@bp.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        raw_phone = request.form.get("phone", "").strip()
        phone = normalize_phone(raw_phone) if raw_phone else None
        password = request.form.get("password", "")
        age = request.form.get("age")
        if not full_name or not email or not valid_password(password):
            flash("Enter your name and a password with 8+ characters, uppercase, lowercase, number, and special character.", "error")
        elif raw_phone and phone is None:
            flash("Phone number must be exactly 10-digit with numbers only.", "error")
        elif age is not None and age != "" and (not age.isdigit() or int(age) < 18):
            flash("Age must be 18 or above.", "error")
        elif password != request.form.get("confirm_password"):
            flash("Passwords do not match.", "error")
        elif User.query.filter(db.func.lower(User.email) == email).first():
            flash("An account with that email already exists.", "error")
        else:
            user = User(full_name=full_name, email=email, phone=phone, password_hash=generate_password_hash(password))
            db.session.add(user)
            db.session.flush()
            profile = PatientProfile(user_id=user.id)
            if age and age.isdigit():
                profile.age = int(age)
            db.session.add(profile)
            db.session.add(UserSettings(user_id=user.id))
            db.session.commit()
            flash("Account created. Please sign in.", "success")
            return redirect(url_for("main.login"))
    return render_template("auth.html", mode="register")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter_by(email=email).first()
        if not user or not user.active or not check_password_hash(user.password_hash, password):
            flash("Email or password is incorrect.", "error")
        else:
            session.clear()
            session["user_id"] = user.id
            if user.role == "admin":
                return redirect(url_for("main.admin_dashboard"))
            return redirect(url_for("main.dashboard"))
    return render_template("auth.html", mode="login")


@bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("main.login"))


@bp.route("/dashboard")
@login_required
def dashboard():
    user = current_user()
    today = date.today()
    schedules = MedicineSchedule.query.join(Medicine).filter(Medicine.user_id == user.id).all()
    due = [item for item in schedules if schedule_runs_today(item, today)]
    logs = prepare_reminders(user.id)
    statuses = {schedule_id: log.status for schedule_id, log in logs.items()}
    water = sum((log.amount_ml or 0) for log in WaterLog.query.filter_by(user_id=user.id).filter(db.func.date(WaterLog.logged_at) == today).all())
    activities = DailyActivity.query.filter_by(user_id=user.id, activity_date=today).all()
    completed = sum(1 for activity in activities if activity.logs and activity.logs[-1].status == "Completed")
    low_stock = Medicine.query.filter(Medicine.user_id == user.id, Medicine.quantity <= Medicine.low_stock_threshold).all()
    ending = Medicine.query.filter(Medicine.user_id == user.id, Medicine.end_date == today + timedelta(days=2)).all()
    notifications = Notification.query.filter_by(user_id=user.id).order_by(Notification.created_at.desc()).limit(5).all()
    settings = user.settings or UserSettings(user_id=user.id)
    if not settings.water_target_ml or settings.water_target_ml <= 0:
        settings.water_target_ml = 2000
        db.session.add(settings)
        db.session.commit()
    return render_template("dashboard.html", user=user, due=due, statuses=statuses, taken=sum(v == "Taken" for v in statuses.values()), water=water or 0, water_target=settings.water_target_ml, activities=activities, completed=completed, low_stock=low_stock, ending=ending, notifications=notifications)


@bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    user = current_user()
    profile = user.profile or PatientProfile(user_id=user.id)
    if request.method == "POST":
        user.full_name = request.form.get("full_name", "").strip() or user.full_name
        user.phone = normalize_phone(request.form.get("phone", "")) or user.phone
        if request.form.get("phone", "") and normalize_phone(request.form.get("phone", "")) is None:
            flash("Contact number must be exactly 10 digits.", "error")
            return render_template("profile.html", user=user, profile=profile)
        age_value = request.form.get("age", "")
        if age_value and (not age_value.isdigit() or int(age_value) < 18):
            flash("Age must be 18 or above.", "error")
            return render_template("profile.html", user=user, profile=profile)
        profile.age = int(age_value) if age_value else None
        profile.gender = request.form.get("gender", "").strip()
        profile.emergency_contact = request.form.get("emergency_contact", "").strip()
        profile.caregiver_info = request.form.get("caregiver_info", "").strip()
        db.session.add(profile)
        db.session.commit()
        flash("Profile updated.", "success")
    return render_template("profile.html", user=user, profile=profile)


@bp.route("/medicines", methods=["GET", "POST"])
@login_required
def medicines():
    user = current_user()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        dosage = request.form.get("dosage", "").strip()
        quantity = integer_value(request.form.get("quantity"), minimum=0)
        threshold = integer_value(request.form.get("low_stock_threshold"), minimum=0)
        if not name or not dosage:
            flash("Medicine name and prescribed dosage are required.", "error")
        elif quantity is None or threshold is None:
            flash("Medicine quantity and low-stock threshold must be whole numbers only.", "error")
        else:
            start_date = parse_date(request.form.get("start_date"))
            end_date = parse_date(request.form.get("end_date"))
            if end_date and start_date and end_date < start_date:
                flash("End date cannot be before the start date.", "error")
                return render_template("medicines.html", medicines=Medicine.query.filter_by(user_id=user.id).all())
            medicine = Medicine(user_id=user.id, name=name, dosage=dosage, quantity=quantity, low_stock_threshold=threshold, start_date=start_date, end_date=end_date, instructions=request.form.get("instructions", "").strip(), notes=request.form.get("notes", "").strip())
            db.session.add(medicine)
            db.session.commit()
            flash("Medicine added.", "success")
            return redirect(url_for("main.medicines"))
    query = request.args.get("q", "").strip()
    medicine_query = Medicine.query.filter_by(user_id=user.id)
    if query:
        medicine_query = medicine_query.filter(Medicine.name.ilike(f"%{query}%"))
    return render_template("medicines.html", medicines=medicine_query.order_by(Medicine.name).all())


@bp.route("/medicines/<int:medicine_id>/edit", methods=["GET", "POST"])
@login_required
def edit_medicine(medicine_id):
    medicine = Medicine.query.filter_by(id=medicine_id, user_id=session["user_id"]).first_or_404()
    if request.method == "POST":
        quantity = integer_value(request.form.get("quantity"), minimum=0)
        threshold = integer_value(request.form.get("low_stock_threshold"), minimum=0)
        start_date = parse_date(request.form.get("start_date"))
        end_date = parse_date(request.form.get("end_date"))
        if quantity is None or threshold is None:
            flash("Medicine quantity and low-stock threshold must be whole numbers only.", "error")
        elif end_date and start_date and end_date < start_date:
            flash("End date cannot be before the start date.", "error")
        else:
            medicine.name = request.form.get("name", "").strip() or medicine.name
            medicine.dosage = request.form.get("dosage", "").strip() or medicine.dosage
            medicine.quantity = quantity
            medicine.low_stock_threshold = threshold
            medicine.start_date = start_date
            medicine.end_date = end_date
            medicine.instructions = request.form.get("instructions", "").strip()
            medicine.notes = request.form.get("notes", "").strip()
            db.session.commit()
            flash("Medicine updated.", "success")
            return redirect(url_for("main.medicines"))
    return render_template("medicine_edit.html", medicine=medicine)


@bp.route("/medicine-history")
@login_required
def medicine_history():
    query = MedicineLog.query.filter_by(user_id=session["user_id"]).join(MedicineSchedule).join(Medicine)
    status = request.args.get("status")
    if status in {"Upcoming", "Taken", "Skipped", "Missed", "Remind Later"}:
        query = query.filter(MedicineLog.status == status)
    search = request.args.get("search", "").strip()
    if search:
        query = query.filter(Medicine.name.ilike(f"%{search}%"))
    selected_date = parse_date(request.args.get("date"))
    if selected_date:
        query = query.filter(MedicineLog.event_date == selected_date)
    logs = query.order_by(MedicineLog.event_date.desc(), MedicineLog.created_at.desc()).all()
    return render_template("history.html", logs=logs)


@bp.post("/medicines/<int:medicine_id>/delete")
@login_required
def delete_medicine(medicine_id):
    medicine = Medicine.query.filter_by(id=medicine_id, user_id=session["user_id"]).first_or_404()
    db.session.delete(medicine)
    db.session.commit()
    flash("Medicine deleted.", "success")
    return redirect(url_for("main.medicines"))


@bp.route("/medicines/<int:medicine_id>/schedule", methods=["GET", "POST"])
@login_required
def schedule(medicine_id):
    medicine = Medicine.query.filter_by(id=medicine_id, user_id=session["user_id"]).first_or_404()
    if request.method == "POST":
        schedule_time = parse_time(request.form.get("time"))
        start_date = parse_date(request.form.get("start_date")) or date.today()
        end_date = parse_date(request.form.get("end_date"))
        frequency = request.form.get("frequency", "Daily")
        if schedule_time is None:
            flash("Enter a valid reminder time.", "error")
        elif end_date and end_date < start_date:
            flash("End date cannot be before the start date.", "error")
        elif frequency not in {"Once", "Daily", "Weekly"}:
            flash("Choose a valid reminder frequency.", "error")
        else:
            schedule_item = MedicineSchedule(medicine_id=medicine.id, time=schedule_time, start_date=start_date, end_date=end_date, frequency=frequency)
            db.session.add(schedule_item)
            db.session.commit()
            flash("Reminder schedule saved.", "success")
            return redirect(url_for("main.medicines"))
    return render_template("schedule.html", medicine=medicine)


@bp.post("/schedules/<int:schedule_id>/delete")
@login_required
def delete_schedule(schedule_id):
    schedule_item = MedicineSchedule.query.join(Medicine).filter(MedicineSchedule.id == schedule_id, Medicine.user_id == session["user_id"]).first_or_404()
    db.session.delete(schedule_item)
    db.session.commit()
    flash("Reminder schedule deleted.", "success")
    return redirect(url_for("main.medicines"))


@bp.post("/medicine-log/<int:schedule_id>/<status>")
@login_required
def medicine_log(schedule_id, status):
    schedule_item = MedicineSchedule.query.join(Medicine).filter(MedicineSchedule.id == schedule_id, Medicine.user_id == session["user_id"]).first_or_404()
    if status not in {"Taken", "Skipped", "Remind Later"}:
        flash("Unsupported status.", "error")
    else:
        log = MedicineLog.query.filter_by(schedule_id=schedule_item.id, user_id=session["user_id"], event_date=date.today()).first()
        if not log:
            log = MedicineLog(schedule_id=schedule_item.id, user_id=session["user_id"], event_date=date.today())
            db.session.add(log)
        previous_status = log.status
        if status == "Remind Later":
            log.snoozed_until = datetime.now() + timedelta(minutes=30)
        log.status = status
        if status == "Taken" and previous_status != "Taken":
            schedule_item.medicine.quantity = max(0, schedule_item.medicine.quantity - 1)
        db.session.commit()
        flash(f"Marked {schedule_item.medicine.name} as {status.lower()}.", "success")
    return redirect(url_for("main.dashboard"))


@bp.post("/notifications/<int:notification_id>/read")
@login_required
def mark_notification_read(notification_id):
    notification = Notification.query.filter_by(id=notification_id, user_id=session["user_id"]).first_or_404()
    notification.is_read = True
    db.session.commit()
    return redirect(url_for("main.notifications"))


@bp.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    user = current_user()
    user_settings = user.settings or UserSettings(user_id=session["user_id"])
    if request.method == "POST":
        try:
            target = int(float(request.form.get("water_target_ml", "0")) * 1000)
            if target <= 0:
                raise ValueError
            user_settings.water_target_ml = target
            user_settings.water_reminder_times = request.form.get("water_reminder_times", "").strip()
            user_settings.reminder_enabled = bool(request.form.get("reminder_enabled"))
            user_settings.reminder_sound = request.form.get("reminder_sound", "On")
            user_settings.vibration = bool(request.form.get("vibration"))
            user_settings.notification_timing_minutes = int(request.form.get("notification_timing_minutes", "10") or 10)
            user_settings.push_notifications = bool(request.form.get("push_notifications"))
            user_settings.email_notifications = bool(request.form.get("email_notifications"))
            user_settings.default_reminder_time = request.form.get("default_reminder_time", "08:00")
            user_settings.snooze_duration = int(request.form.get("snooze_duration", "10") or 10)
            user_settings.repeat_missed = bool(request.form.get("repeat_missed"))
            user_settings.time_zone = request.form.get("time_zone", "Asia/Kolkata")
            user_settings.time_format = request.form.get("time_format", "12-hour")
            user_settings.date_format = request.form.get("date_format", "DD/MM/YYYY")
            user_settings.theme = request.form.get("theme", "Light")
            user_settings.language = request.form.get("language", "English")
            user_settings.caregiver_name = request.form.get("caregiver_name", "").strip()
            user_settings.caregiver_contact = request.form.get("caregiver_contact", "").strip()
            user_settings.caregiver_access = bool(request.form.get("caregiver_access"))
            user.full_name = request.form.get("full_name", user.full_name).strip() or user.full_name
            raw_phone = request.form.get("phone", "").strip()
            if raw_phone and normalize_phone(raw_phone) is None:
                raise ValueError
            user.phone = normalize_phone(raw_phone) or user.phone
            new_password = request.form.get("password", "")
            if new_password:
                if not valid_password(new_password):
                    raise ValueError
                user.password_hash = generate_password_hash(new_password)
            db.session.add(user)
            db.session.add(user_settings)
            db.session.commit()
            flash("Settings updated.", "success")
        except ValueError:
            flash("Please enter valid numeric values in the settings form.", "error")
    access = CaregiverAccess.query.filter_by(user_id=user.id, active=True).first()
    caregiver_url = url_for("main.caregiver_dashboard", token=access.token, _external=True) if access else None
    return render_template("settings.html", settings=user_settings, user=user, caregiver_url=caregiver_url)


@bp.route("/water", methods=["GET", "POST"])
@login_required
def water():
    if request.method == "POST":
        amount_ml = request.form.get("amount_ml")
        if amount_ml is None or amount_ml == "":
            amount_ml = request.form.get("amount_liters")
            if amount_ml is not None:
                try:
                    amount_ml = int(float(amount_ml) * 1000)
                except ValueError:
                    amount_ml = None
        else:
            try:
                amount_ml = int(amount_ml)
            except ValueError:
                amount_ml = None
        if amount_ml is not None and amount_ml > 0:
            db.session.add(WaterLog(user_id=session["user_id"], amount_ml=amount_ml))
            db.session.commit()
            flash("Water intake recorded.", "success")
        else:
            flash("Enter a valid amount in litres.", "error")
    logs = WaterLog.query.filter_by(user_id=session["user_id"]).order_by(WaterLog.logged_at.desc()).limit(30).all()
    today_total = sum(log.amount_ml for log in WaterLog.query.filter_by(user_id=session["user_id"]).filter(db.func.date(WaterLog.logged_at) == date.today()).all())
    return render_template("water.html", logs=logs, total=today_total)


@bp.route("/activities", methods=["GET", "POST"])
@login_required
def activities():
    if request.method == "POST":
        activity = DailyActivity(user_id=session["user_id"], name=request.form.get("name", "").strip(), time=parse_time(request.form.get("time")), activity_date=parse_date(request.form.get("activity_date")) or date.today(), frequency=request.form.get("frequency", "Once"))
        if not activity.name:
            flash("Activity name is required.", "error")
        else:
            db.session.add(activity)
            db.session.commit()
            flash("Activity added.", "success")
    items = DailyActivity.query.filter_by(user_id=session["user_id"]).order_by(DailyActivity.activity_date, DailyActivity.time).all()
    return render_template("activities.html", activities=items)


@bp.post("/activities/<int:activity_id>/<status>")
@login_required
def activity_status(activity_id, status):
    activity = DailyActivity.query.filter_by(id=activity_id, user_id=session["user_id"]).first_or_404()
    if status in {"Completed", "Skipped", "Pending"}:
        db.session.add(ActivityLog(activity_id=activity.id, status=status))
        db.session.commit()
    return redirect(url_for("main.activities"))


@bp.route("/health", methods=["GET", "POST"])
@login_required
def health():
    if request.method == "POST":
        record = HealthRecord(user_id=session["user_id"], metric=request.form.get("metric", "").strip(), value=request.form.get("value", "").strip(), notes=request.form.get("notes", "").strip())
        if record.metric and record.value:
            db.session.add(record)
            db.session.commit()
            flash("Health record saved.", "success")
    records = HealthRecord.query.filter_by(user_id=session["user_id"]).order_by(HealthRecord.recorded_at.desc()).all()
    return render_template("health.html", records=records)


@bp.route("/notifications")
@login_required
def notifications():
    items = Notification.query.filter_by(user_id=session["user_id"]).order_by(Notification.created_at.desc()).all()
    return render_template("notifications.html", notifications=items)


@bp.get("/api/notifications/unread")
@login_required
def unread_notifications():
    items = Notification.query.filter_by(user_id=session["user_id"], is_read=False).order_by(Notification.created_at.desc()).limit(10).all()
    return jsonify([{"id": item.id, "title": item.title, "message": item.message} for item in items])


@bp.route("/reports")
@login_required
def reports():
    user_id = session["user_id"]
    today = date.today()
    prepare_reminders(user_id, target=today)
    period = request.args.get("period", "week")
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")
    if start_date and end_date:
        start = parse_date(start_date) or (today - timedelta(days=6))
        end = parse_date(end_date) or today
    elif period == "today":
        start = today
        end = today
    elif period == "month":
        start = today.replace(day=1)
        end = today
    else:
        start = today - timedelta(days=6)
        end = today
    logs = MedicineLog.query.filter(MedicineLog.user_id == user_id, MedicineLog.event_date >= start, MedicineLog.event_date <= end).order_by(MedicineLog.event_date.desc()).all()
    water_logs = WaterLog.query.filter(WaterLog.user_id == user_id, WaterLog.logged_at >= datetime.combine(start, time.min), WaterLog.logged_at <= datetime.combine(end, time.max)).all()
    status = request.args.get("status")
    if status in {"Taken", "Skipped", "Missed", "Upcoming", "Remind Later"}:
        logs = [log for log in logs if log.status == status]
    filtered_water = sum(log.amount_ml for log in water_logs)
    return render_template("reports.html", logs=logs, water_total=filtered_water, week_start=start, today=end, period=period, start_date=start.isoformat(), end_date=end.isoformat(), total_taken=sum(1 for log in logs if log.status == "Taken"), total_skipped=sum(1 for log in logs if log.status in {"Skipped", "Missed"}), total_doses=len(logs))


@bp.get("/reports/export.csv")
@login_required
def export_reports():
    user_id = session["user_id"]
    end = parse_date(request.args.get("end_date")) or date.today()
    start = parse_date(request.args.get("start_date")) or (end - timedelta(days=6))
    logs = MedicineLog.query.filter(MedicineLog.user_id == user_id, MedicineLog.event_date >= start, MedicineLog.event_date <= end).order_by(MedicineLog.event_date, MedicineLog.created_at).all()
    water = WaterLog.query.filter(WaterLog.user_id == user_id, WaterLog.logged_at >= datetime.combine(start, time.min), WaterLog.logged_at <= datetime.combine(end, time.max)).all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Date", "Type", "Name", "Status", "Amount (L)"])
    for log in logs:
        writer.writerow([log.event_date.isoformat(), "Medicine", log.schedule.medicine.name, log.status, ""])
    for entry in water:
        writer.writerow([entry.logged_at.date().isoformat(), "Water", "", "Logged", f"{entry.amount_ml / 1000:.2f}"])
    return Response(output.getvalue(), mimetype="text/csv", headers={"Content-Disposition": f"attachment; filename=daily-care-{start.isoformat()}-{end.isoformat()}.csv"})


@bp.post("/caregiver/access")
@login_required
def create_caregiver_access():
    user = current_user()
    settings = user.settings or UserSettings(user_id=user.id)
    settings.caregiver_access = True
    access = CaregiverAccess.query.filter_by(user_id=user.id, active=True).first()
    if not access:
        access = CaregiverAccess(user_id=user.id, token=secrets.token_urlsafe(32), label=request.form.get("label", "Caregiver").strip() or "Caregiver")
        db.session.add(access)
    db.session.add(settings)
    db.session.commit()
    flash("Caregiver access link is ready.", "success")
    return redirect(url_for("main.settings"))


@bp.post("/caregiver/access/revoke")
@login_required
def revoke_caregiver_access():
    user = current_user()
    access = CaregiverAccess.query.filter_by(user_id=user.id, active=True).first()
    if access:
        access.active = False
    if user.settings:
        user.settings.caregiver_access = False
    db.session.commit()
    flash("Caregiver access revoked.", "success")
    return redirect(url_for("main.settings"))


@bp.get("/caregiver/<token>")
def caregiver_dashboard(token):
    access = CaregiverAccess.query.filter_by(token=token, active=True).first_or_404()
    user = db.session.get(User, access.user_id)
    today = date.today()
    logs = MedicineLog.query.filter_by(user_id=user.id, event_date=today).order_by(MedicineLog.created_at.desc()).all()
    medicines = Medicine.query.filter_by(user_id=user.id).order_by(Medicine.name).all()
    water_total = sum(entry.amount_ml for entry in WaterLog.query.filter_by(user_id=user.id).filter(db.func.date(WaterLog.logged_at) == today).all())
    return render_template("caregiver.html", user=user, logs=logs, medicines=medicines, water_total=water_total, today=today)


@bp.route("/admin")
@login_required
def admin_dashboard():
    user = current_user()
    if user.role != "admin":
        flash("Access denied. Admin only.", "error")
        return redirect(url_for("main.dashboard"))
    total_users = User.query.count()
    total_medicines = Medicine.query.count()
    total_reminders = MedicineSchedule.query.count()
    total_doses = MedicineLog.query.count()
    taken = MedicineLog.query.filter_by(status="Taken").count()
    skipped = MedicineLog.query.filter(MedicineLog.status.in_(["Skipped", "Missed"])).count()
    recent_users = User.query.order_by(User.created_at.desc()).limit(10).all()
    recent_logs = MedicineLog.query.order_by(MedicineLog.created_at.desc()).limit(8).all()
    return render_template("admin.html", total_users=total_users, total_medicines=total_medicines, total_reminders=total_reminders, total_doses=total_doses, taken=taken, skipped=skipped, recent_users=recent_users, recent_logs=recent_logs)


@bp.post("/admin/users/<int:user_id>/toggle")
@login_required
def toggle_user_status(user_id):
    admin = current_user()
    if admin.role != "admin":
        flash("Access denied. Admin only.", "error")
        return redirect(url_for("main.dashboard"))
    target = User.query.get_or_404(user_id)
    if target.id == admin.id:
        flash("The signed-in admin account cannot be deactivated.", "error")
    else:
        target.active = not target.active
        db.session.commit()
        flash(f"{target.full_name} is now {'active' if target.active else 'inactive'}.", "success")
    return redirect(url_for("main.admin_dashboard"))
