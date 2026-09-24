from datetime import date, datetime

from .models import User
from .routes import prepare_reminders


def run_reminder_cycle(app, target=None, now=None):
    """Generate persistent reminders for every active user once."""
    with app.app_context():
        users = User.query.filter_by(active=True).all()
        for user in users:
            prepare_reminders(user.id, target=target or date.today(), now=now or datetime.now())
        return len(users)