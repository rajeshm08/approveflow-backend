import argparse
import os
import shutil
from pathlib import Path

from sqlalchemy.engine import make_url

from app.config import settings
from app.database import Base, engine
from app import models  # noqa: F401
from seed_demo_data import seed


def is_demo_database() -> bool:
    if os.getenv("SEED_DEMO_DATA", "").strip().lower() == "true":
        return True
    url = make_url(settings.database_url)
    if url.get_backend_name() != "sqlite":
        return False
    database_path = url.database
    if not database_path or database_path == ":memory:":
        return False
    name = Path(database_path).name.lower()
    return name == "approveflow.db" or ("approveflow" in name and ("demo" in name or "e2e" in name))


def clear_uploads() -> None:
    upload_directory = settings.upload_directory
    if not upload_directory.exists():
        return
    for item in upload_directory.iterdir():
        if item.is_symlink() or item.is_file():
            item.unlink()
        elif item.is_dir():
            shutil.rmtree(item)


def validate_upload_directory() -> None:
    upload_directory = settings.upload_directory.resolve()
    project_directory = Path(__file__).resolve().parent
    protected_roots = {Path(upload_directory.anchor), Path.home().resolve(), project_directory}
    if upload_directory in protected_roots:
        raise ValueError("Refusing to clear a filesystem, home, or project root as the uploads directory.")
    if "upload" not in upload_directory.name.lower():
        raise ValueError("UPLOAD_DIRECTORY must name a dedicated uploads folder.")
    if project_directory in upload_directory.parents and upload_directory.parent != project_directory:
        raise ValueError("Refusing to clear a nested project directory as the uploads folder.")
    if settings.upload_directory.is_symlink():
        raise ValueError("Refusing to clear a symlink configured as the uploads directory.")


def reset_database() -> None:
    url = make_url(settings.database_url)
    engine.dispose()
    if url.get_backend_name() == "sqlite":
        database_path = url.database
        if not database_path or database_path == ":memory:":
            Base.metadata.drop_all(bind=engine)
            return
        path = Path(database_path)
        if not path.is_absolute():
            path = Path.cwd() / path
        for candidate in (path, Path(f"{path}-wal"), Path(f"{path}-shm")):
            if candidate.is_file():
                candidate.unlink()
    else:
        Base.metadata.drop_all(bind=engine)


def main() -> None:
    parser = argparse.ArgumentParser(description="Reset and reseed the local ApproveFlow demo database.")
    parser.add_argument("--yes", action="store_true", help="Skip the interactive reset confirmation.")
    args = parser.parse_args()

    if not is_demo_database():
        parser.error(
            "Refusing to reset a non-demo database. Set SEED_DEMO_DATA=true only after verifying "
            "DATABASE_URL points to a disposable demo database."
        )
    try:
        validate_upload_directory()
    except ValueError as error:
        parser.error(str(error))
    if not args.yes:
        safe_database_url = make_url(settings.database_url).render_as_string(hide_password=True)
        confirmation = input(
            f"This will delete and reseed the database at {safe_database_url!r} "
            "and clear the configured uploads folder. Continue? [y/N] "
        )
        if confirmation.strip().lower() not in {"y", "yes"}:
            print("Reset cancelled.")
            return

    reset_database()
    clear_uploads()
    seed()


if __name__ == "__main__":
    main()
