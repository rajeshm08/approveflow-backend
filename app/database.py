from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import normalize_database_url, settings

database_url = normalize_database_url(settings.database_url)
connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
engine = create_engine(database_url, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def ensure_extension_columns() -> None:
    extensions = {
        "documents": {
            "document_type": "VARCHAR(100)",
            "storage_key": "VARCHAR(80)",
            "content_type": "VARCHAR(100)",
            "size_bytes": "INTEGER",
            "expires_at": "TIMESTAMP",
        },
        "notifications": {
            "application_id": "INTEGER",
            "deduplication_key": "VARCHAR(240)",
            "notification_type": "VARCHAR(60)",
            "delivery_status": "VARCHAR(30)",
        },
        "escalations": {
            "document_id": "INTEGER REFERENCES documents(id)",
            "deduplication_key": "VARCHAR(240)",
            "escalation_level": "VARCHAR(60)",
            "resolved_by": "INTEGER",
            "resolved_at": "TIMESTAMP",
        },
        "undertakings": {
            "submitted_at": "TIMESTAMP",
        },
    }
    with engine.begin() as connection:
        inspector = inspect(connection)
        for table_name, columns in extensions.items():
            if not inspector.has_table(table_name):
                continue
            existing = {column["name"] for column in inspector.get_columns(table_name)}
            for column_name, column_type in columns.items():
                if column_name not in existing:
                    connection.execute(
                        text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")
                    )
        connection.execute(
            text("CREATE UNIQUE INDEX IF NOT EXISTS uq_notifications_deduplication_key "
                 "ON notifications (deduplication_key)")
        )
        connection.execute(
            text("CREATE UNIQUE INDEX IF NOT EXISTS uq_escalations_deduplication_key "
                 "ON escalations (deduplication_key)")
        )
