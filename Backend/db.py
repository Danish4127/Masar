import os
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy import create_engine

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL not found. Check your .env file.")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)


def run_schema(schema_path: str = "schema.sql"):
    from sqlalchemy import text

    schema_file = Path(schema_path)
    if not schema_file.is_absolute():
        schema_file = Path(__file__).resolve().parent / schema_file
    with open(schema_file, "r", encoding="utf-8") as f:
        sql = f.read()

    with engine.begin() as conn:
        for statement in sql.split(";"):
            statement = statement.strip()
            if statement:
                conn.execute(text(statement))
    print("Schema applied to Neon database.")


if __name__ == "__main__":
    from sqlalchemy import text

    with engine.connect() as conn:
        result = conn.execute(text("SELECT version();"))
        print("Connected:", result.fetchone()[0])
