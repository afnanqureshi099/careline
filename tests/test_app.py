from datetime import date, time
import pytest
from app import create_app, db
from app.models import Medicine, MedicineSchedule, MedicineLog, WaterLog, DailyActivity, HealthRecord


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
    with client.application.app_context():
        assert Medicine.query.one().quantity == 4
        assert MedicineLog.query.one().status == "Taken"


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
