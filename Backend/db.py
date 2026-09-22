import os
import re
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv(Path(__file__).resolve().parent / ".env")

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL not found. Copy .env.example to .env and set it.")
                                                                                        
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = "postgresql://" + DATABASE_URL[len("postgres://"):]

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,                                                     
    pool_recycle=1800,
    pool_size=int(os.getenv("DB_POOL_SIZE", "10")),
    max_overflow=int(os.getenv("DB_MAX_OVERFLOW", "20")),
)

def run_schema(schema_path: str = "schema.sql") -> None:
    """Apply schema.sql. Every statement is idempotent (IF NOT EXISTS), so this is safe on every start."""
    schema_file = Path(schema_path)
    if not schema_file.is_absolute():
        schema_file = Path(__file__).resolve().parent / schema_file
    sql = schema_file.read_text(encoding="utf-8")
    sql = re.sub(r"--[^\n]*", "", sql)                                          
    with engine.begin() as conn:
        for statement in sql.split(";"):
            statement = statement.strip()
            if statement:
                conn.execute(text(statement))

if __name__ == "__main__":
    with engine.connect() as conn:
        print("Connected:", conn.execute(text("SELECT version();")).fetchone()[0])
