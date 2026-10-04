from sqlalchemy import select

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db_models import ManagedService, User

def create_managed_service(
        session: Session, 
        name: str, 
        display_name: str,
        runtime_type: str = "docker",
        runtime_name: str | None = None
        ) -> ManagedService:
    service = ManagedService(
        name=name, 
        display_name=display_name,
        runtime_type=runtime_type,
        runtime_name=runtime_name or name
    )

    try:
        session.add(service)
        session.commit()
        session.refresh(service)

        return service
    except IntegrityError:
        session.rollback()
        raise

def get_managed_services(db: Session) -> list[ManagedService]:
    statement = select(ManagedService).order_by(ManagedService.id)
    return list(db.scalars(statement).all())

def get_user_by_username(db: Session, username: str) -> User | None:
    statement = select(User).where(User.username == username)
    return db.scalar(statement)