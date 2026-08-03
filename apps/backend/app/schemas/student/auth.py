from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, model_validator


class StudentRegisterRequest(BaseModel):
    email: Optional[str] = Field(None, max_length=200)
    phone: Optional[str] = Field(None, max_length=30)
    password: str = Field(..., min_length=6, max_length=72)
    nickname: Optional[str] = Field(None, max_length=100)

    @model_validator(mode="after")
    def require_account(self):
        email = (self.email or "").strip() or None
        phone = (self.phone or "").strip() or None
        self.email = email
        self.phone = phone
        if not email and not phone:
            raise ValueError("请填写手机号或邮箱")
        return self


class StudentLoginRequest(BaseModel):
    account: str = Field(..., description="手机号或邮箱")
    password: str


class StudentProfileUpdate(BaseModel):
    nickname: Optional[str] = Field(None, max_length=100)
    password: Optional[str] = Field(None, min_length=6, max_length=72)


class UserPublic(BaseModel):
    id: int
    email: Optional[str] = None
    phone: Optional[str] = None
    nickname: Optional[str] = None
    role: str
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserPublic
