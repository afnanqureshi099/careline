from datetime import date, datetime, timedelta, time
import pytest
from app import create_app, db
from app.reminders import run_reminder_cycle
from app.models import CaregiverAccess, Medicine, MedicineSchedule, MedicineLog, Notification, WaterLog, DailyActivity, HealthRecord, User, UserSettings


@pytest.fixture
def client():
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:", "WTF_CSRF_ENABLED": False})
    with app.test_client() as client:
        yield client
    with app.app_context():
        db.drop_all()


def register_and_login(client):
    client.post("/register", data={"full_name": "Test User", "email": "test@example.com", "password": "Valid@123", "confirm_password": "Valid@123"})
    return client.post("/login", data={"email": "test@example.com", "password": "Valid@123"})


def test_registration_and_invalid_login(client):
    response = client.post("/register", data={"full_name": "Test", "email": "test@example.com", "password": "weak", "confirm_password": "weak"}, follow_redirects=True)
    assert b"password with 8+ characters" in response.data
    register_and_login(client)
    client.get("/logout")
    response = client.post("/login", data={"email": "test@example.com", "password": "wrong"}, follow_redirects=True)
    assert b"incorrect" in response.data
    duplicate = client.post("/register", data={"full_name": "Test User", "email": "test@example.com", "password": "Valid@123", "confirm_password": "Valid@123"}, follow_redirects=True)
    assert b"already exists" in duplicate.data


def test_password_change_and_inactive_session_are_enforced(client):
    register_and_login(client)
    response = client.post("/settings", data={"water_target_ml": "2", "password": "NewValid@456"}, follow_redirects=True)
    assert response.status_code == 200
    client.get("/logout")
    assert client.post("/login", data={"email": "test@example.com", "password": "NewValid@456"}).status_code == 302
    with client.application.app_context():
        user = User.query.filter_by(email="test@example.com").one()
        user.active = False
        db.session.commit()
    response = client.get("/dashboard", follow_redirects=True)
    assert b"account is inactive" in response.data


def test_protected_pages_require_login(client):
    response = client.get("/dashboard")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]
    assert client.get("/reports/export.csv").status_code == 302


def test_phone_and_age_validation(client):
    response = client.post("/register", data={"full_name": "Test User", "email": "phone@example.com", "phone": "12345", "password": "Valid@123", "confirm_password": "Valid@123"}, follow_redirects=True)
    assert b"10-digit" in response.data
    response = client.post("/register", data={"full_name": "Test User", "email": "age@example.com", "phone": "9876543210", "password": "Valid@123", "confirm_password": "Valid@123", "age": "17"}, follow_redirects=True)
    assert b"18" in response.data or b"above 18" in response.data


def test_medicine_schedule_log_and_quantity(client):
    register_and_login(client)
    client.post("/medicines", data={"name": "Example Medicine", "dosage": "1 tablet", "quantity": "5", "low_stock_threshold": "2", "start_date": str(date.today())})
    with client.application.app_context():
        medicine = Medicine.query.one()
        schedule = MedicineSchedule(medicine_id=medicine.id, time=time(8), start_date=date.today(), frequency="Daily")
        db.session.add(schedule)
        db.session.commit()
        schedule_id = schedule.id
    response = client.post(f"/medicine-log/{schedule_id}/Taken", follow_redirects=True)
    assert response.status_code == 200
    client.post(f"/medicine-log/{schedule_id}/Taken")
    with client.application.app_context():
        assert Medicine.query.one().quantity == 4
        assert MedicineLog.query.one().status == "Taken"


def test_invalid_schedule_and_edit_values_are_rejected(client):
    register_and_login(client)
    client.post("/medicines", data={"name": "Example", "dosage": "1 tablet", "quantity": "5", "low_stock_threshold": "1", "start_date": str(date.today())})
    with client.application.app_context():
        medicine = Medicine.query.filter_by(name="Example").one()
        medicine_id = medicine.id
    response = client.post(f"/medicines/{medicine_id}/schedule", data={"time": "not-a-time", "start_date": str(date.today()), "frequency": "Daily"}, follow_redirects=True)
    assert b"valid reminder time" in response.data
    response = client.post(f"/medicines/{medicine_id}/edit", data={"name": "Example", "dosage": "1 tablet", "quantity": "1.5", "low_stock_threshold": "1", "start_date": str(date.today())}, follow_redirects=True)
    assert b"whole numbers" in response.data


def test_water_activity_health_records(client):
    register_and_login(client)
    assert client.post("/water", data={"amount_ml": "250"}).status_code == 200
    assert client.post("/activities", data={"name": "Walk", "activity_date": str(date.today())}).status_code == 200
    assert client.post("/health", data={"metric": "Weight", "value": "70 kg", "notes": "manual"}).status_code == 200
    with client.application.app_context():
        assert WaterLog.query.one().amount_ml == 250
        assert DailyActivity.query.one().name == "Walk"
        assert HealthRecord.query.one().value == "70 kg"


def test_ownership_blocks_other_user(client):
    register_and_login(client)
    client.post("/medicines", data={"name": "Private", "dosage": "1"})
    client.get("/logout")
    client.post("/register", data={"full_name": "Other", "email": "other@example.com", "password": "Valid@123", "confirm_password": "Valid@123"})
    client.post("/login", data={"email": "other@example.com", "password": "Valid@123"})
    assert client.get("/medicines").status_code == 200
    assert b"Private" not in client.get("/medicines").data


def test_user_data_persists_across_logout_and_other_user_session(client):
    register_and_login(client)
    client.post("/medicines", data={"name": "Persistent Medicine", "dosage": "1 tablet", "quantity": "7", "low_stock_threshold": "2"})
    client.post("/water", data={"amount_liters": "0.6"})
    client.get("/logout")
    client.post("/register", data={"full_name": "Second User", "email": "second@example.com", "password": "Valid@123", "confirm_password": "Valid@123"})
    client.post("/login", data={"email": "second@example.com", "password": "Valid@123"})
    client.post("/medicines", data={"name": "Second Medicine", "dosage": "1 capsule", "quantity": "3", "low_stock_threshold": "1"})
    assert b"Persistent Medicine" not in client.get("/medicines").data
    client.get("/logout")
    client.post("/login", data={"email": "test@example.com", "password": "Valid@123"})
    medicines_page = client.get("/medicines")
    assert b"Persistent Medicine" in medicines_page.data
    assert b"Second Medicine" not in medicines_page.data
    assert b"0.60" in client.get("/water").data


def test_default_admin_bootstrap():
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:", "WTF_CSRF_ENABLED": False})
    with app.app_context():
        admin = User.query.filter_by(role="admin").first()
        assert admin is not None
        assert admin.email == "admin@dailycare.local"


def test_admin_and_reports_count(client):
    register_and_login(client)
    client.post("/medicines", data={"name": "Paracetamol", "dosage": "1 tablet", "quantity": "5", "low_stock_threshold": "2", "start_date": str(date.today()), "end_date": str(date.today() + timedelta(days=2))})
    with client.application.app_context():
        user = User.query.filter_by(email="test@example.com").first()
        medicine = Medicine.query.filter_by(user_id=user.id).first()
        schedule = MedicineSchedule(medicine_id=medicine.id, time=time(8), start_date=date.today(), end_date=date.today() + timedelta(days=2), frequency="Daily")
        db.session.add(schedule)
        db.session.commit()
        MedicineLog.query.filter_by(user_id=user.id).delete()
        db.session.add(MedicineLog(schedule_id=schedule.id, user_id=user.id, event_date=date.today(), status="Taken"))
        db.session.add(MedicineLog(schedule_id=schedule.id, user_id=user.id, event_date=date.today(), status="Skipped"))
        db.session.add(WaterLog(user_id=user.id, amount_ml=250))
        db.session.commit()
    response = client.get("/reports")
    assert b"Taken" in response.data
    assert b"Skipped" in response.data
    assert b"0.25" in response.data or b"0.25 L" in response.data

    with client.application.app_context():
        user = User.query.filter_by(email="test@example.com").first()
        user.role = "admin"
        db.session.commit()
    response = client.get("/admin")
    assert response.status_code == 200
    assert b"Admin" in response.data

    with client.application.app_context():
        User.query.filter_by(email="test@example.com").one().role = "user"
        db.session.commit()
    client.get("/logout")
    client.post("/login", data={"email": "test@example.com", "password": "Valid@123"})
    assert client.get("/admin").status_code == 302


def test_caregiver_link_is_read_only_and_revocable(client):
    register_and_login(client)
    response = client.post("/caregiver/access", follow_redirects=True)
    assert response.status_code == 200
    with client.application.app_context():
        access = CaregiverAccess.query.one()
        token = access.token
    response = client.get(f"/caregiver/{token}")
    assert response.status_code == 200
    assert b"Caregiver view" in response.data
    client.post("/caregiver/access/revoke")
    assert client.get(f"/caregiver/{token}").status_code == 404


def test_report_export_and_litre_settings(client):
    register_and_login(client)
    client.post("/water", data={"amount_liters": "0.75"})
    response = client.get("/reports/export.csv")
    assert response.status_code == 200
    assert response.mimetype == "text/csv"
    assert b"Amount (L)" in response.data
    assert b"0.75" in response.data
    client.post("/settings", data={"water_target_ml": "2.5"})
    with client.application.app_context():
        user = User.query.filter_by(email="test@example.com").one()
        assert UserSettings.query.filter_by(user_id=user.id).one().water_target_ml == 2500


def test_admin_can_deactivate_and_reactivate_user(client):
    register_and_login(client)
    client.get("/logout")
    client.post("/register", data={"full_name": "Other", "email": "other@example.com", "password": "Valid@123", "confirm_password": "Valid@123"})
    with client.application.app_context():
        user = User.query.filter_by(email="other@example.com").one()
        user_id = user.id
    client.post("/login", data={"email": "admin@dailycare.local", "password": "Admin@123"})
    response = client.post(f"/admin/users/{user_id}/toggle", follow_redirects=True)
    assert response.status_code == 200
    with client.application.app_context():
        assert User.query.get(user_id).active is False
    client.get("/logout")
    response = client.post("/login", data={"email": "other@example.com", "password": "Valid@123"}, follow_redirects=True)
    assert b"incorrect" in response.data
    client.post("/login", data={"email": "admin@dailycare.local", "password": "Admin@123"})
    client.post(f"/admin/users/{user_id}/toggle")
    with client.application.app_context():
        assert User.query.get(user_id).active is True


def test_reminders_notifications_history_profile_and_activity(client):
    register_and_login(client)
    client.post("/medicines", data={"name": "Reminder Medicine", "dosage": "1 tablet", "quantity": "3", "low_stock_threshold": "1", "start_date": str(date.today())})
    with client.application.app_context():
        user = User.query.filter_by(email="test@example.com").one()
        user_id = user.id
        medicine = Medicine.query.filter_by(user_id=user.id).one()
        reminder_time = (datetime.now() + timedelta(minutes=2)).time().replace(second=0, microsecond=0)
        schedule = MedicineSchedule(medicine_id=medicine.id, time=reminder_time, start_date=date.today(), frequency="Daily")
        db.session.add(schedule)
        db.session.commit()
        schedule_id = schedule.id
    response = client.get("/dashboard")
    assert response.status_code == 200
    with client.application.app_context():
        assert Notification.query.filter_by(user_id=user_id).count() >= 1
    client.post(f"/medicine-log/{schedule_id}/Remind Later")
    with client.application.app_context():
        log = MedicineLog.query.filter_by(schedule_id=schedule_id).one()
        log.snoozed_until = datetime.now() - timedelta(minutes=1)
        db.session.commit()
    client.get("/dashboard")
    assert b"Reminder Medicine" in client.get("/medicine-history?status=Upcoming").data
    notification_id = None
    with client.application.app_context():
        notification_id = Notification.query.filter_by(user_id=user_id).order_by(Notification.created_at.desc()).first().id
    client.post(f"/notifications/{notification_id}/read")
    with client.application.app_context():
        assert Notification.query.get(notification_id).is_read is True
    client.post("/profile", data={"full_name": "Updated User", "phone": "9876543210", "age": "30", "gender": "Other"})
    assert b"Updated User" in client.get("/profile").data
    client.post("/activities", data={"name": "Stretch", "activity_date": str(date.today()), "time": "08:00", "frequency": "Daily"})
    with client.application.app_context():
        activity = DailyActivity.query.filter_by(name="Stretch").one()
        activity_id = activity.id
    assert client.post(f"/activities/{activity_id}/Completed").status_code == 302


def test_background_reminder_cycle_persists_notifications_without_page_visit(client):
    register_and_login(client)
    client.post("/medicines", data={"name": "Worker Medicine", "dosage": "1 tablet", "quantity": "5", "low_stock_threshold": "1", "start_date": str(date.today())})
    with client.application.app_context():
        user = User.query.filter_by(email="test@example.com").one()
        medicine = Medicine.query.filter_by(user_id=user.id).one()
        schedule = MedicineSchedule(medicine_id=medicine.id, time=time(9), start_date=date.today(), frequency="Daily")
        db.session.add(schedule)
        db.session.commit()
        user_id = user.id
    processed = run_reminder_cycle(client.application, target=date.today(), now=datetime.combine(date.today(), time(9, 1)))
    assert processed == 2
    with client.application.app_context():
        assert Notification.query.filter_by(user_id=user_id).count() >= 1
        assert MedicineLog.query.filter_by(user_id=user_id, event_date=date.today()).one().status == "Missed"
    response = client.get("/api/notifications/unread")
    assert response.status_code == 200
    assert response.is_json
    assert response.json
