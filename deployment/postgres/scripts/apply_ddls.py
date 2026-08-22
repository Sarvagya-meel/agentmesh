from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv

MIGRATION_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS agentmesh_schema_migrations (
    file_name TEXT PRIMARY KEY,
    checksum TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


def normalise_connection_url(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://", 1)


def default_ddls_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "ddls"


def checksum_sql(sql: str) -> str:
    return hashlib.sha256(sql.encode("utf-8")).hexdigest()


def apply_ddls(database_url: str, ddls_dir: Path, *, dry_run: bool = False) -> None:
    ddl_files = sorted(ddls_dir.glob("*.sql"))
    if not ddl_files:
        raise SystemExit(f"No DDL files found in {ddls_dir}")

    with psycopg.connect(normalise_connection_url(database_url), autocommit=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute(MIGRATION_TABLE_DDL)
            for ddl_file in ddl_files:
                sql = ddl_file.read_text(encoding="utf-8")
                digest = checksum_sql(sql)
                cursor.execute(
                    "SELECT checksum FROM agentmesh_schema_migrations WHERE file_name = %s",
                    (ddl_file.name,),
                )
                row = cursor.fetchone()

                if row is not None and row[0] == digest:
                    print(f"skip {ddl_file.name}")
                    continue

                action = "update" if row is not None else "apply"
                print(f"{action} {ddl_file.name}")
                if dry_run:
                    continue

                with connection.transaction():
                    cursor.execute(sql)
                    cursor.execute(
                        """
                        INSERT INTO agentmesh_schema_migrations (file_name, checksum)
                        VALUES (%s, %s)
                        ON CONFLICT (file_name) DO UPDATE SET
                            checksum = EXCLUDED.checksum,
                            updated_at = CURRENT_TIMESTAMP
                        """,
                        (ddl_file.name, digest),
                    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apply AgentMesh PostgreSQL DDL files.")
    parser.add_argument(
        "--database-url",
        default=os.getenv("DATABASE_URL"),
        help="PostgreSQL URL. Defaults to DATABASE_URL from environment or .env.",
    )
    parser.add_argument(
        "--ddls-dir",
        type=Path,
        default=default_ddls_dir(),
        help="Directory containing ordered *.sql DDL files.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print actions without executing SQL.",
    )
    return parser.parse_args()


def main() -> None:
    load_dotenv()
    args = parse_args()
    database_url = args.database_url or os.getenv("DATABASE_URL")
    if not database_url:
        raise SystemExit("DATABASE_URL is required.")
    apply_ddls(database_url, args.ddls_dir, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
