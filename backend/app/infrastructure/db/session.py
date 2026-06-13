from collections.abc import Generator
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from app.infrastructure.settings import get_settings


settings = get_settings()

connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from app.infrastructure.db.models import Base

    Base.metadata.create_all(bind=engine)
    _ensure_runtime_columns()


def _ensure_runtime_columns() -> None:
    inspector = inspect(engine)
    if "conversations" not in inspector.get_table_names():
        return
    conversation_columns = {column["name"] for column in inspector.get_columns("conversations")}
    workspace_columns = {column["name"] for column in inspector.get_columns("workspaces")}
    dialect = engine.dialect.name
    datetime_type = "DATETIME" if dialect == "sqlite" else "TIMESTAMP WITH TIME ZONE"
    conversation_missing_columns = {
        "title": "VARCHAR(120)",
        "memory_summary": "TEXT",
        "memory_updated_at": datetime_type,
        "memory_message_cursor": "VARCHAR(36)",
    }
    workspace_missing_columns = {
        "voice_style_preference": "VARCHAR(40) DEFAULT 'auto'",
    }
    with engine.begin() as connection:
        for column_name, column_type in conversation_missing_columns.items():
            if column_name not in conversation_columns:
                connection.execute(text(f"ALTER TABLE conversations ADD COLUMN {column_name} {column_type}"))
        for column_name, column_type in workspace_missing_columns.items():
            if column_name not in workspace_columns:
                connection.execute(text(f"ALTER TABLE workspaces ADD COLUMN {column_name} {column_type}"))
