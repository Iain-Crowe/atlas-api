from getpass import getpass

from sqlalchemy import select

from app.database import SessionLocal
from app.db_models import User, UserRole
from app.security import hash_password


def main():
    username = input("Admin username: ").strip()
    password = getpass("Password: ")
    confirm_password = getpass("Confirm password: ")

    if not username:
        raise SystemExit("Username cannot be empty")

    if not password:
        raise SystemExit("Password cannot be empty")

    if password != confirm_password:
        raise SystemExit("Passwords do not match")

    with SessionLocal() as db:
        existing_user = db.scalar(
            select(User).where(User.username == username)
        )

        if existing_user:
            raise SystemExit("User already exists")

        user = User(
            username=username,
            password_hash=hash_password(password),
            role=UserRole.ADMIN.value,
            active=True,
        )

        db.add(user)
        db.commit()
        db.refresh(user)

        print(f"Created admin user '{user.username}' with id {user.id}")


if __name__ == "__main__":
    main()