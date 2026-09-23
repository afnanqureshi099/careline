from flask import Flask
from sqlalchemy import inspect, text
from flask_sqlalchemy import SQLAlchemy
from config import Config


db = SQLAlchemy()


def upgrade_existing_schema():
    columns = {column["name"] for column in inspect(db.engine).get_columns("medicine_log")}
    if "snoozed_until" not in columns:
        db.session.execute(text("ALTER TABLE medicine_log ADD COLUMN snoozed_until DATETIME"))
    columns = {column["name"] for column in inspect(db.engine).get_columns("notification")}
    if "notification_key" not in columns:
        db.session.execute(text("ALTER TABLE notification ADD COLUMN notification_key VARCHAR(180)"))
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

    return app
