"""Test setup.

Tests that touch the database need a THROW-AWAY PostgreSQL database, given via
MASAR_TEST_DATABASE_URL. We deliberately never fall back to DATABASE_URL so the
suite can not accidentally seed or modify your real (Neon) database.

    createdb masar_test
    MASAR_TEST_DATABASE_URL=postgresql://user:pass@localhost/masar_test pytest
"""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

TEST_DB = os.getenv("MASAR_TEST_DATABASE_URL")

os.environ["DATABASE_URL"] = TEST_DB or "postgresql://nobody:nothing@localhost:1/none"
os.environ["AUTH_SECRET"] = "test-secret-test-secret-test-secret"
os.environ["AI_EXPLANATION_ENABLED"] = "false"
os.environ["EMAIL_DEV_CONSOLE"] = "true"
os.environ.pop("EMAIL_PROVIDER", None)

def _need_db():
    if not TEST_DB:
        pytest.skip("set MASAR_TEST_DATABASE_URL to a throw-away PostgreSQL database to run this test")

@pytest.fixture(scope="session")
def db():
    _need_db()
    import seed_db
    seed_db.seed_database()
    from db import engine
    return engine

@pytest.fixture(scope="session")
def courses(db):
    from recommender import get_courses_df
    df = get_courses_df()
    return {r.course_code: r for r in df.itertuples()}
