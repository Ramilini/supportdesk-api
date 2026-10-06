from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, require_roles
from app.core.security import authenticate_user, create_access_token, get_password_hash
from app.models.user import Role, User
from app.schemas.user import Token, UserCreate, UserLogin, UserRead, UserRoleUpdate

router = APIRouter(prefix="", tags=["auth"])


@router.post(
    "/auth/register",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
)
def register_user(
    payload: UserCreate, db: Session = Depends(get_db)
) -> User:
    email = str(payload.email)
    existing_user = db.scalar(select(User).where(User.email == email))
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User with this email already exists",
        )

    user = User(
        email=email,
        hashed_password=get_password_hash(payload.password),
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if db.scalar(select(User.id).where(User.email == email)) is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="User with this email already exists",
            ) from exc
        raise
    db.refresh(user)
    return user


@router.post("/auth/login", response_model=Token)
def login_user(
    payload: UserLogin, db: Session = Depends(get_db)
) -> Token:
    user = authenticate_user(db, str(payload.email), payload.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = create_access_token(subject=user.email)
    return Token(access_token=token)


@router.get("/users/me", response_model=UserRead)
def get_current_user_profile(
    current_user: User = Depends(get_current_user),
) -> User:
    return current_user


@router.get("/users/", response_model=list[UserRead])
def list_users(
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(Role.AGENT, Role.ADMIN)),
) -> list[User]:
    return list(db.scalars(select(User).order_by(User.id)).all())


@router.patch("/users/{user_id}/role", response_model=UserRead)
def update_user_role(
    user_id: int,
    payload: UserRoleUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(Role.ADMIN)),
) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    user.role = payload.role
    db.commit()
    db.refresh(user)
    return user
