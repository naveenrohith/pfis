"""Create authenticated synthetic users and financial fixtures for E2E runs."""

from __future__ import annotations

# ruff: noqa: E402
import argparse
import asyncio
import json
import os
import secrets
import sys
import uuid
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.database import normalize_async_database_url
from app.models.email import RawEmail
from app.models.sync import BackgroundJob, JobStatus
from app.models.user import User
from app.security import create_auth_session, hash_password
from app.services.financial_clock import user_financial_today
from app.services.gmail.demo_data import sample_emails_for_date
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from scripts.e2e_safety import (
    E2EGuardError,
    e2e_database_name,
    parse_postgres_target,
    validate_fixture_write,
)

PROFILE_MODES = {
    "pipeline": "demo",
    "restart": "demo",
    "mock_demo": "demo",
    "quick_add": "auth",
    "owner": "auth",
    "other_user": "auth",
    "auth_flow": "auth",
    "planning": "auth",
    "privacy": "auth",
    "statement": "auth",
}
CORPUS_PATH = ROOT / "tests" / "fixtures" / "e2e" / "source-corpus-v1.json"


def _load_corpus() -> dict:
    return json.loads(CORPUS_PATH.read_text(encoding="utf-8"))


def _write_private_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    with suppress(OSError):
        path.chmod(0o600)


async def _verify_target(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    database_url: str,
    database_name: str,
    run_id: str,
) -> None:
    row_query = text(
        """
        SELECT current_database() AS database_name,
               current_user AS role_name,
               shobj_description(
                   (SELECT oid FROM pg_database WHERE datname = current_database()),
                   'pg_database'
               ) AS database_comment,
               role.rolsuper AS is_superuser,
               role.rolcreatedb AS can_create_database,
               role.rolcreaterole AS can_create_role
        FROM pg_roles AS role
        WHERE role.rolname = current_user
        """
    )
    async with session_factory() as session:
        row = (await session.execute(row_query)).mappings().one()
        validate_fixture_write(
            env=dict(os.environ),
            database_url=database_url,
            database_name=row["database_name"],
            run_id=run_id,
            database_comment=row["database_comment"],
        )
        if database_name != e2e_database_name(run_id):
            raise E2EGuardError(
                "--database-name must match the exact database generated for this run"
            )
        if row["database_name"] != database_name:
            raise E2EGuardError("Connected database does not match --database-name")
        if row["is_superuser"] or row["can_create_database"] or row["can_create_role"]:
            raise E2EGuardError("Fixtures must use the least-privilege E2E application role")


def _storage_state(
    *, base_url: str, session_token: str, csrf_token: str, expires_at: datetime
) -> dict:
    hostname = urlsplit(base_url).hostname
    if hostname is None:
        raise E2EGuardError("--base-url must identify the loopback PFIS server")
    expiry = expires_at.timestamp()
    return {
        "cookies": [
            {
                "name": "pfis_session",
                "value": session_token,
                "domain": hostname,
                "path": "/",
                "expires": expiry,
                "httpOnly": True,
                "secure": False,
                "sameSite": "Lax",
            },
            {
                "name": "pfis_csrf",
                "value": csrf_token,
                "domain": hostname,
                "path": "/",
                "expires": expiry,
                "httpOnly": False,
                "secure": False,
                "sameSite": "Lax",
            },
        ],
        "origins": [],
    }


async def _create_profile(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    profile: str,
    run_id: str,
    base_url: str,
    output_dir: Path,
    corpus: dict,
) -> tuple[dict, dict]:
    password = secrets.token_urlsafe(24)
    email = f"pfis-e2e-{run_id}-{profile}@example.com"
    user = User(
        id=str(uuid.uuid4()),
        email=email,
        name=f"PFIS E2E {profile.replace('_', ' ').title()}",
        currency="INR",
        timezone="Asia/Kolkata",
        password_hash=hash_password(password),
        is_active=True,
    )
    profile_data: dict = {
        "profile": profile,
        "user_id": user.id,
        "email": email,
        "currency": "INR",
        "session_mode": PROFILE_MODES[profile],
        "storage_state": f"{profile}.storage-state.json",
        "financial_day": None,
        "financial_period": None,
    }
    expected_credentials = {"email": email, "password": password}

    async with session_factory() as session:
        session.add(user)
        await session.flush()
        financial_day = await user_financial_today(session, user.id)
        profile_data["financial_day"] = financial_day.isoformat()
        profile_data["financial_period"] = {
            "month": financial_day.month,
            "year": financial_day.year,
        }
        session_token, csrf_token, auth_session = await create_auth_session(
            session,
            user.id,
            mode=PROFILE_MODES[profile],
        )
        if profile in {"pipeline", "restart"}:
            source_spec = corpus["source"]
            source_date = financial_day.strftime("%d-%m-%Y")
            body = source_spec["body_template"].format(date=source_date)
            demo_source = sample_emails_for_date(financial_day)[0]
            if (
                any(source_spec[key] != demo_source[key] for key in ("sender", "subject"))
                or body != demo_source["body"]
            ):
                raise RuntimeError(
                    "Versioned E2E source no longer matches the application demo source"
                )
            source_identity = f"demo_{uuid.uuid5(uuid.NAMESPACE_DNS, body[:50])}"
            raw_email = RawEmail(
                user_id=user.id,
                gmail_message_id=f"{user.id}:{source_identity}",
                subject=source_spec["subject"],
                body=body,
                sender=source_spec["sender"],
                received_at=datetime.now(UTC),
                processed_flag=False,
            )
            session.add(raw_email)
            await session.flush()
            profile_data.update(
                {
                    "source_raw_email_id": raw_email.id,
                    "source_identity": source_identity,
                    "expected": {
                        "corpus_version": corpus["version"],
                        "classification": corpus["classification"],
                        **corpus["expected_transaction"],
                        "date": financial_day.isoformat(),
                        **corpus["expected_journey"],
                    },
                }
            )
        await session.commit()

    state = _storage_state(
        base_url=base_url,
        session_token=session_token,
        csrf_token=csrf_token,
        expires_at=auth_session.expires_at,
    )
    _write_private_json(output_dir / profile_data["storage_state"], state)
    return profile_data, expected_credentials


async def seed_profiles(args: argparse.Namespace) -> None:
    database_url = os.environ.get("DATABASE_URL", "")
    parse_postgres_target(database_url, expected_database=args.database_name)
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    if not output_dir.is_relative_to((ROOT / ".test-run").resolve()):
        raise E2EGuardError(
            "Fixture credentials and browser state must stay under the ignored .test-run directory"
        )
    base_url = args.base_url.rstrip("/")
    parsed_base = urlsplit(base_url)
    if parsed_base.scheme != "http" or parsed_base.hostname not in {
        "127.0.0.1",
        "localhost",
        "::1",
    }:
        raise E2EGuardError("Fixture base URL must be a local HTTP PFIS address")
    if not args.profiles or len(args.profiles) != len(set(args.profiles)):
        raise E2EGuardError("At least one unique --profile must be requested")
    unknown = sorted(set(args.profiles) - set(PROFILE_MODES))
    if unknown:
        raise E2EGuardError(f"Unknown fixture profile: {unknown[0]}")

    engine = create_async_engine(normalize_async_database_url(database_url), pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        await _verify_target(
            session_factory,
            database_url=database_url,
            database_name=args.database_name,
            run_id=args.run_id,
        )
        corpus = _load_corpus()
        profiles: dict[str, dict] = {}
        credentials: dict[str, dict] = {}
        for profile in args.profiles:
            profile_data, profile_credentials = await _create_profile(
                session_factory,
                profile=profile,
                run_id=args.run_id,
                base_url=base_url,
                output_dir=output_dir,
                corpus=corpus,
            )
            profiles[profile] = profile_data
            credentials[profile] = profile_credentials
        manifest = {
            "schema_version": 1,
            "run_id": args.run_id,
            "database": args.database_name,
            "base_url": base_url,
            "source_corpus_version": corpus["version"],
            "profiles": profiles,
        }
        _write_private_json(output_dir / "manifest.json", manifest)
        _write_private_json(output_dir / "credentials.json", credentials)
    finally:
        await engine.dispose()


async def prepare_restart_job(args: argparse.Namespace) -> str:
    database_url = os.environ.get("DATABASE_URL", "")
    parse_postgres_target(database_url, expected_database=args.database_name)
    output_dir = Path(args.output_dir).resolve()
    if not output_dir.is_relative_to((ROOT / ".test-run").resolve()):
        raise E2EGuardError("Fixture manifests must stay under the ignored .test-run directory")
    manifest_path = output_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("run_id") != args.run_id or manifest.get("database") != args.database_name:
        raise E2EGuardError("E2E manifest does not match the requested run and database")
    profile = manifest.get("profiles", {}).get("restart")
    if not profile:
        raise E2EGuardError("The interrupted-job profile was not seeded for this run")

    engine = create_async_engine(normalize_async_database_url(database_url), pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        await _verify_target(
            session_factory,
            database_url=database_url,
            database_name=args.database_name,
            run_id=args.run_id,
        )
        now = datetime.now(UTC)
        job_id = str(uuid.uuid4())
        async with session_factory() as session:
            session.add(
                BackgroundJob(
                    id=job_id,
                    user_id=profile["user_id"],
                    job_type="demo_sync_pipeline",
                    status=JobStatus.RUNNING,
                    payload_json=json.dumps({"limit": 50}),
                    result_json="{}",
                    attempt_count=1,
                    max_attempts=3,
                    available_at=now,
                    lease_owner=f"pfis-e2e-crashed-{args.run_id}",
                    lease_expires_at=now + timedelta(hours=1),
                    idempotency_key=f"pfis-e2e-restart-{args.run_id}",
                    created_at=now,
                    started_at=now,
                )
            )
            await session.commit()
        profile["recovery_job_id"] = job_id
        _write_private_json(manifest_path, manifest)
        return job_id
    finally:
        await engine.dispose()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    seed_parser = subparsers.add_parser(
        "seed", help="create user, source, session, and storage-state fixtures"
    )
    seed_parser.add_argument("--run-id", required=True)
    seed_parser.add_argument("--database-name", required=True)
    seed_parser.add_argument("--confirm-database", required=True)
    seed_parser.add_argument("--base-url", required=True)
    seed_parser.add_argument("--output-dir", required=True)
    seed_parser.add_argument(
        "--profile", action="append", dest="profiles", choices=tuple(PROFILE_MODES)
    )
    restart_parser = subparsers.add_parser(
        "prepare-restart-job", help="persist one interrupted synthetic job for restart recovery"
    )
    restart_parser.add_argument("--run-id", required=True)
    restart_parser.add_argument("--database-name", required=True)
    restart_parser.add_argument("--confirm-database", required=True)
    restart_parser.add_argument("--output-dir", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    args.run_id = args.run_id.lower()
    if e2e_database_name(args.run_id) != args.database_name:
        raise E2EGuardError("--database-name must exactly match pfis_e2e_<run-id>")
    if args.confirm_database != args.database_name:
        raise E2EGuardError("--confirm-database must exactly match --database-name")
    if os.environ.get("PFIS_E2E") != "1":
        raise E2EGuardError("Fixture writes require explicit PFIS_E2E=1")
    if os.environ.get("PFIS_E2E_RUN_ID") != args.run_id:
        raise E2EGuardError("--run-id must match PFIS_E2E_RUN_ID")
    if os.environ.get("PFIS_E2E_CONFIRM_DATABASE") != args.database_name:
        raise E2EGuardError(
            "Exact database confirmation environment does not match the requested target"
        )
    if args.command == "seed":
        asyncio.run(seed_profiles(args))
        print(
            f"Created {len(args.profiles)} authenticated E2E fixture profile(s); raw credentials were not printed."
        )
    else:
        job_id = asyncio.run(prepare_restart_job(args))
        print(f"Prepared interrupted synthetic background job {job_id}.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (E2EGuardError, ValueError) as exc:
        print(f"E2E fixture refused: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
