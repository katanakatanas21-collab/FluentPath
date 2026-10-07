"""Create or reset local teacher and administrator development accounts."""

import getpass
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import server


if os.getenv("FLUENT_PATH_ENVIRONMENT", "development").lower() != "development":
    raise SystemExit("Refusing to seed accounts outside FLUENT_PATH_ENVIRONMENT=development")

server.DATA_DIR = Path(__file__).resolve().parent / "data"
server.STUDENTS_FILE = server.DATA_DIR / "students.json"


def password_for(label):
    password = getpass.getpass(f"Set {label} development password (16+ characters): ")
    confirmation = getpass.getpass("Confirm password: ")
    if password != confirmation:
        raise SystemExit("Passwords do not match")
    if len(password) < 16:
        raise SystemExit("Development passwords must be at least 16 characters")
    return password


def upsert_account(accounts, *, user_id, name, email, role, password):
    existing = next((user for user in accounts if user.get("email", "").lower() == email), None)
    if existing and not existing.get("devOnly"):
        raise SystemExit(f"Refusing to change non-development account: {email}")

    account = existing or {
        "id": user_id,
        "fullName": name,
        "email": email,
        "dateOfBirth": "",
        "phone": "",
        "level": None,
        "testScore": None,
        "totalQuestions": None,
        "testCompletedAt": None,
        "courseProgress": {},
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }
    account.update({
        "fullName": name,
        "email": email,
        "passwordHash": server.hash_password(password),
        "role": role,
        "devOnly": True,
    })
    if existing is None:
        accounts.append(account)


def main():
    passwords = {
        "teacher": password_for("teacher"),
        "administrator": password_for("administrator"),
    }
    accounts = server.load_students()
    upsert_account(
        accounts,
        user_id="dev-teacher-local",
        name="Teacher Development Account",
        email="teacher.dev@fluentpath.local",
        role="teacher",
        password=passwords["teacher"],
    )
    upsert_account(
        accounts,
        user_id="dev-admin-local",
        name="Administrator Development Account",
        email="admin.dev@fluentpath.local",
        role="administrator",
        password=passwords["administrator"],
    )
    server.save_students(accounts)
    print("Development-only teacher and administrator accounts are ready.")
    print("Passwords were stored as salted hashes and were not written to source files.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError) as error:
        print(f"Unable to seed development accounts: {error}", file=sys.stderr)
        raise SystemExit(1) from error