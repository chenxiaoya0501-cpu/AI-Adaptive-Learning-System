from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_student
from app.core.security import create_access_token, hash_password, verify_password
from app.database import get_db
from app.models.user import User
from app.schemas.student.auth import (
    StudentLoginRequest,
    StudentProfileUpdate,
    StudentRegisterRequest,
    TokenResponse,
    UserPublic,
)

router = APIRouter(prefix="/auth")


def _to_public(user: User) -> UserPublic:
    return UserPublic.model_validate(user)


def _issue_token(user: User) -> TokenResponse:
    token = create_access_token(
        subject=str(user.id),
        extra={"role": user.role},
    )
    return TokenResponse(access_token=token, user=_to_public(user))


@router.post("/register", response_model=TokenResponse)
async def register(body: StudentRegisterRequest, db: AsyncSession = Depends(get_db)):
    conds = []
    if body.email:
        conds.append(User.email == body.email)
    if body.phone:
        conds.append(User.phone == body.phone)
    if conds:
        existing = (await db.execute(select(User).where(or_(*conds)))).scalar_one_or_none()
        if existing:
            raise HTTPException(status_code=400, detail="该手机号或邮箱已注册")

    nickname = (body.nickname or "").strip() or (body.email or body.phone or "学生")
    user = User(
        email=body.email,
        phone=body.phone,
        password_hash=hash_password(body.password),
        nickname=nickname,
        role="student",
        is_active=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return _issue_token(user)


@router.post("/login", response_model=TokenResponse)
async def login(body: StudentLoginRequest, db: AsyncSession = Depends(get_db)):
    account = body.account.strip()
    result = await db.execute(
        select(User).where(
            or_(User.email == account, User.phone == account),
            User.role == "student",
        )
    )
    user = result.scalar_one_or_none()
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="账号或密码错误")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="账号已停用")
    return _issue_token(user)


@router.get("/me", response_model=UserPublic)
async def me(user: User = Depends(get_current_student)):
    return _to_public(user)


@router.put("/me", response_model=UserPublic)
async def update_me(
    body: StudentProfileUpdate,
    user: User = Depends(get_current_student),
    db: AsyncSession = Depends(get_db),
):
    if body.nickname is not None:
        nick = body.nickname.strip()
        if nick:
            user.nickname = nick
    if body.password:
        user.password_hash = hash_password(body.password)
    await db.commit()
    await db.refresh(user)
    return _to_public(user)
