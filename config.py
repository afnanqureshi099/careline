import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-change-me")
    ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@dailycare.local")
    ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "Admin@123")
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL", f"sqlite:///{os.path.join(BASE_DIR, 'care.db')}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
