from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models.user import Role


class PasswordCredentials(BaseModel):
    password: str = Field(min_length=8)

    model_config = ConfigDict(extra="forbid")

    @field_validator("password")
    @classmethod
    def validate_bcrypt_password_length(cls, password: str) -> str:
        if len(password.encode("utf-8")) > 72:
            raise ValueError("Password must not exceed 72 UTF-8 bytes")
        return password


class UserCreate(PasswordCredentials):
    email: EmailStr


class UserLogin(PasswordCredentials):
    email: EmailStr


class UserRead(BaseModel):
    id: int
    email: EmailStr
    role: Role
    created_at: datetime
    updated_at: datetime
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


UserResponse = UserRead


class UserRoleUpdate(BaseModel):
    role: Role

    model_config = ConfigDict(extra="forbid")


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
