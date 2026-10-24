from app.config import normalize_database_url


def test_postgresql_url_schemes_use_installed_psycopg_driver_and_keep_sslmode():
    assert normalize_database_url(
        "postgres://demo:secret@ep-example.neon.tech/approveflow?sslmode=require"
    ) == (
        "postgresql+psycopg://demo:secret@ep-example.neon.tech/approveflow?sslmode=require"
    )
    assert normalize_database_url(
        "postgresql://demo:secret@ep-example.neon.tech/approveflow?sslmode=require"
    ) == (
        "postgresql+psycopg://demo:secret@ep-example.neon.tech/approveflow?sslmode=require"
    )


def test_database_url_already_using_psycopg_or_sqlite_is_unchanged():
    postgres_url = "postgresql+psycopg://demo:secret@localhost/approveflow?sslmode=require"
    sqlite_url = "sqlite:///./approveflow.db"

    assert normalize_database_url(postgres_url) == postgres_url
    assert normalize_database_url(sqlite_url) == sqlite_url
