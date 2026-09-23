import re
from datetime import date, datetime, time, timedelta
from functools import wraps
from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash
from . import db
from .models import (ActivityLog, DailyActivity, HealthRecord, Medicine, MedicineLog,
                     MedicineSchedule, Notification, PatientProfile, User, UserSettings, WaterLog)

bp = Blueprint("main", __name__)


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("main.login"))
        return view(*args, **kwargs)
    return wrapped


def current_user():
    return db.session.get(User, session.get("user_id"))


def valid_password(value):
    return (len(value) >= 8 and re.search(r"[A-Z]", value) and re.search(r"[a-z]", value)
            and re.search(r"\d", value) and re.search(r"[^A-Za-z0-9]", value))


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


def prepare_reminders(user_id, target=None):
    target = target or date.today()
    now = datetime.now()
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
        if item.time and item.time <= now.time() and log.status == "Upcoming":
            log.status = "Missed"
            create_notification(user_id, f"missed-{item.id}-{target}", "Missed medicine reminder", f"{item.medicine.name} was not marked at {item.time.strftime('%I:%M %p')}.")
        elif item.time and item.time >= now.time() and log.status == "Upcoming":
            create_notification(user_id, f"due-{item.id}-{target}", "Medicine due", f"It is time to take {item.medicine.name} at {item.time.strftime('%I:%M %p')}.")
        if item.medicine.quantity <= item.medicine.low_stock_threshold:
            create_notification(user_id, f"stock-{item.medicine.id}-{target}", "Low medicine quantity", f"{item.medicine.name} has {item.medicine.quantity:g} units remaining.")
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
        phone = request.form.get("phone", "").strip()
        password = request.form.get("password", "")
        if not full_name or not email or not valid_password(password):
            flash("Enter your name and a password with 8+ characters, uppercase, lowercase, number, and special character.", "error")
        elif password != request.form.get("confirm_password"):
            flash("Passwords do not match.", "error")
        elif User.query.filter_by(email=email).first():
            flash("An account with that email already exists.", "error")
        else:
            user = User(full_name=full_name, email=email, phone=phone, password_hash=generate_password_hash(password))
            db.session.add(user)
            db.session.flush()
            db.session.add(PatientProfile(user_id=user.id))
            db.session.add(UserSettings(user_id=user.id))
            db.session.commit()
            flash("Account created. Please sign in.", "success")
            return redirect(url_for("main.login"))
    return render_template("auth.html", mode="register")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = User.query.filter_by(email=request.form.get("email", "").strip().lower()).first()
        if not user or not check_password_hash(user.password_hash, request.form.get("password", "")):
            flash("Email or password is incorrect.", "error")
        else:
            session.clear()
            session["user_id"] = user.id
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
        user.phone = request.form.get("phone", "").strip()
        profile.age = int(request.form["age"]) if request.form.get("age", "").isdigit() else None
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
        if not name or not dosage:
            flash("Medicine name and prescribed dosage are required.", "error")
        else:
            start_date = parse_date(request.form.get("start_date"))
            end_date = parse_date(request.form.get("end_date"))
            if end_date and start_date and end_date < start_date:
                flash("End date cannot be before the start date.", "error")
                return render_template("medicines.html", medicines=Medicine.query.filter_by(user_id=user.id).all())
            medicine = Medicine(user_id=user.id, name=name, dosage=dosage, quantity=positive_number(request.form.get("quantity")), low_stock_threshold=positive_number(request.form.get("low_stock_threshold")), start_date=start_date, end_date=end_date, instructions=request.form.get("instructions", "").strip(), notes=request.form.get("notes", "").strip())
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
        medicine.name = request.form.get("name", "").strip() or medicine.name
        medicine.dosage = request.form.get("dosage", "").strip() or medicine.dosage
        medicine.quantity = positive_number(request.form.get("quantity"))
        medicine.low_stock_threshold = positive_number(request.form.get("low_stock_threshold"))
        medicine.start_date = parse_date(request.form.get("start_date"))
        medicine.end_date = parse_date(request.form.get("end_date"))
        medicine.instructions = request.form.get("instructions", "").strip()
        medicine.notes = request.form.get("notes", "").strip()
        db.session.commit()
        flash("Medicine updated.", "success")
        return redirect(url_for("main.medicines"))
    return render_template("medicine_edit.html", medicine=medicine)


@bp.route("/medicine-history")
@login_required
def medicine_history():
    query = MedicineLog.query.filter_by(user_id=session["user_id"])
    if request.args.get("status") in {"Upcoming", "Taken", "Skipped", "Missed", "Remind Later"}:
        query = query.filter_by(status=request.args["status"])
    if request.args.get("date"):
        selected_date = parse_date(request.args["date"])
        if selected_date:
            query = query.filter_by(event_date=selected_date)
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
        schedule_item = MedicineSchedule(medicine_id=medicine.id, time=parse_time(request.form.get("time")), start_date=parse_date(request.form.get("start_date")) or date.today(), end_date=parse_date(request.form.get("end_date")), frequency=request.form.get("frequency", "Daily"))
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
        if status == "Remind Later":
            log.snoozed_until = datetime.now() + timedelta(minutes=30)
        log.status = status
        if status == "Taken":
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
    user_settings = current_user().settings or UserSettings(user_id=session["user_id"])
    if request.method == "POST":
        try:
            target = int(request.form.get("water_target_ml", "0"))
            if target <= 0:
                raise ValueError
            user_settings.water_target_ml = target
            user_settings.water_reminder_times = request.form.get("water_reminder_times", "").strip()
            db.session.add(user_settings)
            db.session.commit()
            flash("Settings updated.", "success")
        except ValueError:
            flash("Water target must be a positive number of millilitres.", "error")
    return render_template("settings.html", settings=user_settings)


@bp.route("/water", methods=["GET", "POST"])
@login_required
def water():
    if request.method == "POST":
        amount = int(request.form.get("amount_ml") or 0)
        if amount > 0:
            db.session.add(WaterLog(user_id=session["user_id"], amount_ml=amount))
            db.session.commit()
            flash("Water intake recorded.", "success")
    logs = WaterLog.query.filter_by(user_id=session["user_id"]).order_by(WaterLog.logged_at.desc()).limit(30).all()
    return render_template("water.html", logs=logs, total=sum(log.amount_ml for log in logs if log.logged_at.date() == date.today()))


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


@bp.route("/reports")
@login_required
def reports():
    user_id = session["user_id"]
    today = date.today()
    week_start = today - timedelta(days=6)
    logs = MedicineLog.query.filter(MedicineLog.user_id == user_id, MedicineLog.event_date >= week_start).all()
    water_logs = WaterLog.query.filter(WaterLog.user_id == user_id, WaterLog.logged_at >= datetime.combine(week_start, time.min)).all()
    return render_template("reports.html", logs=logs, water_total=sum(log.amount_ml for log in water_logs), week_start=week_start, today=today)
