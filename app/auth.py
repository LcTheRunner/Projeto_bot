from __future__ import annotations

import hashlib
import re
import secrets
import smtplib
from dataclasses import dataclass
from datetime import datetime, timedelta
from email.message import EmailMessage
from urllib.parse import quote

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import (
    DashboardSession, DashboardUser, EmailSchedule, EmailVerificationCode,
    PasswordResetToken, UserKeyword,
)


SESSION_COOKIE = "mcs_session"
USERNAME_PATTERN = re.compile(r"^[a-z0-9._-]{3,50}$")
EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


@dataclass(frozen=True)
class CurrentUser:
    id: int
    username: str
    display_name: str
    email: str | None
    admin: bool
    external_email_allowed: bool


class LoginRequest(BaseModel):
    username: str | None = None
    password: str | None = None


class UserRequest(BaseModel):
    username: str | None = None
    displayName: str | None = None
    email: str | None = None
    password: str | None = None
    admin: bool = False


class EmailRequest(BaseModel):
    email: str | None = None


class ResetRequest(BaseModel):
    token: str | None = None
    password: str | None = None


class VerificationRequest(BaseModel):
    username: str | None = None
    code: str | None = None


class PermissionRequest(BaseModel):
    enabled: bool = False


def _now() -> datetime:
    return datetime.now().replace(microsecond=0)


def _clean_username(value: str | None) -> str:
    return (value or "").strip().lower()


def _clean_email(value: str | None) -> str:
    return (value or "").strip().lower()


def _hash_token(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def hash_password(value: str) -> str:
    return bcrypt.hashpw(value.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("ascii")


def verify_password(value: str | None, encoded: str) -> bool:
    try:
        return bcrypt.checkpw((value or "").encode("utf-8"), encoded.encode("ascii"))
    except (ValueError, TypeError):
        return False


def _user_from_row(user: DashboardUser) -> CurrentUser:
    return CurrentUser(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        email=user.email,
        admin=bool(user.is_admin),
        external_email_allowed=bool(user.can_send_external_email),
    )


def user_map(user: CurrentUser) -> dict:
    result = {
        "id": user.id,
        "username": user.username,
        "displayName": user.display_name,
        "admin": user.admin,
        "externalEmailAllowed": user.external_email_allowed,
        "owner": is_configured_owner(user.username, user.email),
    }
    if user.email is not None:
        result["email"] = user.email
    return result


def require_user(request: Request, db: Session = Depends(get_db)) -> CurrentUser:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Autenticação necessária")
    user = db.scalar(
        select(DashboardUser)
        .join(DashboardSession, DashboardSession.user_id == DashboardUser.id)
        .where(
            DashboardSession.token_hash == _hash_token(token),
            DashboardSession.expires_at > _now(),
            DashboardUser.active.is_(True),
        )
    )
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sessão expirada")
    return _user_from_row(user)


def _require_admin(db: Session, actor: CurrentUser, lock: bool = False) -> DashboardUser:
    statement = select(DashboardUser).where(
        DashboardUser.id == actor.id,
        DashboardUser.active.is_(True),
        DashboardUser.is_admin.is_(True),
    )
    if lock:
        statement = statement.with_for_update()
    current = db.scalar(statement)
    if current is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Acesso administrativo necessário")
    return current


def is_configured_owner(username: str | None, email: str | None) -> bool:
    cfg = settings()
    configured_username = _clean_username(cfg.dashboard_owner_username)
    configured_email = _clean_email(cfg.dashboard_owner_email)
    return (
        bool(USERNAME_PATTERN.fullmatch(configured_username))
        and bool(EMAIL_PATTERN.fullmatch(configured_email))
        and configured_username == _clean_username(username)
        and configured_email == _clean_email(email)
    )


def enforce_configured_owner(db: Session) -> None:
    cfg = settings()
    owner_username = _clean_username(cfg.dashboard_owner_username)
    owner_email = _clean_email(cfg.dashboard_owner_email)
    if not USERNAME_PATTERN.fullmatch(owner_username) or not EMAIL_PATTERN.fullmatch(owner_email):
        return
    owner = db.scalar(
        select(DashboardUser).where(
            DashboardUser.username == owner_username,
            DashboardUser.email == owner_email,
            DashboardUser.active.is_(True),
            DashboardUser.email_verified.is_(True),
        )
    )
    if owner is None:
        return
    additional = {
        _clean_username(value)
        for value in cfg.dashboard_additional_admin_usernames.split(",")
        if USERNAME_PATTERN.fullmatch(_clean_username(value))
    }
    additional.discard(owner_username)
    candidates = db.scalars(
        select(DashboardUser).where(
            (DashboardUser.is_admin.is_(True))
            | (DashboardUser.id == owner.id)
            | (DashboardUser.username.in_(additional or {"__none__"}))
        )
    ).all()
    for candidate in candidates:
        candidate.is_admin = bool(
            candidate.id == owner.id
            or (
                candidate.username in additional
                and candidate.active
                and candidate.email_verified
            )
        )
    db.commit()


def _mail_configured() -> None:
    cfg = settings()
    if not cfg.smtp_host.strip() or not cfg.report_from.strip():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "O envio de e-mail ainda não está configurado")


def _send_message(message: EmailMessage) -> None:
    cfg = settings()
    try:
        with smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=20) as smtp:
            smtp.starttls()
            if cfg.smtp_user:
                smtp.login(cfg.smtp_user, cfg.smtp_password)
            smtp.send_message(message)
    except (OSError, smtplib.SMTPException) as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "Não conseguimos enviar o e-mail agora. Tente novamente",
        ) from exc


def _seed_user_keywords(db: Session, user_id: int) -> None:
    from app.migrations import DEFAULT_KEYWORDS

    existing = {
        keyword.casefold()
        for keyword in db.scalars(select(UserKeyword.keyword).where(UserKeyword.user_id == user_id))
    }
    for keyword in DEFAULT_KEYWORDS:
        if keyword.casefold() not in existing:
            db.add(UserKeyword(user_id=user_id, keyword=keyword))


def _create_user(
    db: Session,
    username: str | None,
    display_name: str | None,
    email: str | None,
    password: str | None,
    *,
    admin: bool = False,
    verified: bool = True,
) -> DashboardUser:
    clean_username = _clean_username(username)
    clean_email = _clean_email(email)
    if (
        not USERNAME_PATTERN.fullmatch(clean_username)
        or not EMAIL_PATTERN.fullmatch(clean_email)
        or not password
        or not password.strip()
    ):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Preencha um usuário válido, um e-mail válido e uma senha",
        )
    user = DashboardUser(
        username=clean_username,
        # Java currently stores the username here; preserve its public behavior.
        display_name=clean_username,
        email=clean_email,
        email_verified=verified,
        password_hash=hash_password(password),
        is_admin=admin,
    )
    try:
        db.add(user)
        db.flush()
        _seed_user_keywords(db, user.id)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Usuário ou e-mail já cadastrado") from exc
    db.refresh(user)
    return user


def _send_verification_code(db: Session, user_id: int) -> None:
    _mail_configured()
    user = db.get(DashboardUser, user_id)
    if user is None or not user.email:
        return
    code = f"{secrets.randbelow(1_000_000):06d}"
    record = db.get(EmailVerificationCode, user_id)
    if record is None:
        record = EmailVerificationCode(user_id=user_id, code_hash="", expires_at=_now())
        db.add(record)
    record.code_hash = _hash_token(code)
    record.expires_at = _now() + timedelta(minutes=15)
    record.attempts = 0
    db.commit()
    message = EmailMessage()
    message["From"] = settings().report_from
    message["To"] = user.email
    message["Subject"] = "Código de validação — Central de Monitoramento do MCS"
    message.set_content(
        f"Seu código de validação é:\n\n{code}\n\n"
        "O código expira em 15 minutos. Se você não criou esta conta, ignore este e-mail."
    )
    _send_message(message)


router = APIRouter(prefix="/api/auth", tags=["autenticação"])


@router.post("/login")
def login(body: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    user = db.scalar(
        select(DashboardUser).where(
            DashboardUser.username == _clean_username(body.username),
            DashboardUser.active.is_(True),
        )
    )
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Usuário ou senha inválidos")
    if not user.email_verified:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Confirme o código enviado ao seu e-mail antes de entrar")
    token = secrets.token_urlsafe(32)
    db.add(DashboardSession(
        token_hash=_hash_token(token),
        user_id=user.id,
        expires_at=_now() + timedelta(days=settings().dashboard_session_days),
    ))
    db.commit()
    forwarded_proto = request.headers.get("x-forwarded-proto", "").split(",", 1)[0].strip()
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=settings().dashboard_session_days * 86400,
        httponly=True,
        secure=request.url.scheme == "https" or forwarded_proto.lower() == "https",
        samesite="strict",
        path="/",
    )
    return user_map(_user_from_row(user))


@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        db.execute(delete(DashboardSession).where(DashboardSession.token_hash == _hash_token(token)))
        db.commit()
    forwarded_proto = request.headers.get("x-forwarded-proto", "").split(",", 1)[0].strip()
    response.delete_cookie(
        SESSION_COOKIE,
        path="/",
        httponly=True,
        secure=request.url.scheme == "https" or forwarded_proto.lower() == "https",
        samesite="strict",
    )
    return {"ok": True}


@router.post("/register")
def register(body: UserRequest, db: Session = Depends(get_db)):
    user = _create_user(db, body.username, body.displayName, body.email, body.password, verified=False)
    _send_verification_code(db, user.id)
    return {"id": user.id}


@router.post("/verify-email")
def verify_email(body: VerificationRequest, db: Session = Depends(get_db)):
    user = db.scalar(select(DashboardUser).where(DashboardUser.username == _clean_username(body.username)))
    record = db.get(EmailVerificationCode, user.id) if user else None
    if record is None or record.expires_at <= _now():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Código expirado. Solicite um novo código")
    if record.attempts >= 5:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Muitas tentativas. Solicite um novo código")
    if not body.code or _hash_token(body.code.strip()) != record.code_hash:
        record.attempts += 1
        db.commit()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Código incorreto")
    user.email_verified = True
    db.delete(record)
    db.commit()
    return {"ok": True}


@router.post("/resend-verification")
def resend_verification(body: VerificationRequest, db: Session = Depends(get_db)):
    user = db.scalar(
        select(DashboardUser).where(
            DashboardUser.username == _clean_username(body.username),
            DashboardUser.active.is_(True),
            DashboardUser.email_verified.is_(False),
        )
    )
    if user:
        _send_verification_code(db, user.id)
    return {"ok": True}


@router.post("/forgot-password")
def forgot_password(body: EmailRequest, db: Session = Depends(get_db)):
    user = db.scalar(
        select(DashboardUser).where(
            DashboardUser.email == _clean_email(body.email),
            DashboardUser.active.is_(True),
        )
    )
    if user:
        _mail_configured()
        token = secrets.token_urlsafe(32)
        db.execute(delete(PasswordResetToken).where(PasswordResetToken.user_id == user.id))
        db.add(PasswordResetToken(
            token_hash=_hash_token(token),
            user_id=user.id,
            expires_at=_now() + timedelta(minutes=30),
        ))
        db.commit()
        message = EmailMessage()
        message["From"] = settings().report_from
        message["To"] = user.email
        message["Subject"] = "Redefinição de senha — Central de Monitoramento do MCS"
        base_url = settings().dashboard_public_url.rstrip("/")
        message.set_content(
            "Recebemos uma solicitação para redefinir sua senha.\n\n"
            f"Acesse o link abaixo em até 30 minutos:\n{base_url}/?reset={quote(token)}\n\n"
            "Se você não solicitou esta alteração, ignore este e-mail."
        )
        _send_message(message)
    return {"ok": True}


@router.post("/reset-password")
def reset_password(body: ResetRequest, db: Session = Depends(get_db)):
    if not body.token or not body.token.strip() or not body.password or not body.password.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Link ou senha inválidos")
    record = db.scalar(
        select(PasswordResetToken).where(
            PasswordResetToken.token_hash == _hash_token(body.token),
            PasswordResetToken.expires_at > _now(),
            PasswordResetToken.used_at.is_(None),
        )
    )
    if record is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Link inválido ou expirado")
    user = db.get(DashboardUser, record.user_id)
    user.password_hash = hash_password(body.password)
    record.used_at = _now()
    db.execute(delete(DashboardSession).where(DashboardSession.user_id == user.id))
    db.commit()
    return {"ok": True}


@router.get("/me")
def me(user: CurrentUser = Depends(require_user)):
    return user_map(user)


@router.get("/users")
def list_users(user: CurrentUser = Depends(require_user), db: Session = Depends(get_db)):
    _require_admin(db, user)
    rows = db.scalars(select(DashboardUser).order_by(DashboardUser.created_at.desc())).all()
    result = []
    for row in rows:
        item = {
            "id": row.id,
            "username": row.username,
            "displayName": row.display_name,
            "emailVerified": bool(row.email_verified),
            "admin": bool(row.is_admin),
            "externalEmailAllowed": bool(row.can_send_external_email),
            "active": bool(row.active),
            "createdAt": row.created_at,
            "ownerCandidate": is_configured_owner(row.username, row.email),
        }
        if row.email is not None:
            item["email"] = row.email
        result.append(item)
    return result


@router.post("/users")
def create_user(body: UserRequest, user: CurrentUser = Depends(require_user), db: Session = Depends(get_db)):
    _require_admin(db, user, lock=True)
    if body.admin:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Novas contas são criadas como usuário comum. Use a transferência protegida para alterar o administrador",
        )
    created = _create_user(db, body.username, body.displayName, body.email, body.password)
    return {"id": created.id}


@router.put("/users/{user_id}/owner")
def transfer_ownership(user_id: int, user: CurrentUser = Depends(require_user), db: Session = Depends(get_db)):
    _require_admin(db, user, lock=True)
    target = db.scalar(select(DashboardUser).where(DashboardUser.id == user_id).with_for_update())
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conta não encontrada")
    if not is_configured_owner(target.username, target.email):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "A administração só pode ser transferida para a conta e o e-mail configurados como proprietários",
        )
    if not target.active or not target.email_verified:
        raise HTTPException(status.HTTP_409_CONFLICT, "A conta proprietária precisa estar ativa e com o e-mail confirmado")
    for account in db.scalars(select(DashboardUser).with_for_update()):
        account.is_admin = account.id == target.id
    db.commit()
    return {"updated": True}


@router.put("/users/{user_id}/external-email")
def external_email_permission(
    user_id: int,
    body: PermissionRequest,
    user: CurrentUser = Depends(require_user),
    db: Session = Depends(get_db),
):
    _require_admin(db, user, lock=True)
    if not is_configured_owner(user.username, user.email):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Somente a conta proprietária pode alterar destinos externos")
    target = db.scalar(
        select(DashboardUser).where(DashboardUser.id == user_id, DashboardUser.active.is_(True)).with_for_update()
    )
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conta não encontrada ou inativa")
    target.can_send_external_email = body.enabled
    if not body.enabled:
        db.execute(
            update(EmailSchedule)
            .where(
                EmailSchedule.user_id == user_id,
                EmailSchedule.recipient_email.is_not(None),
                EmailSchedule.status.in_(["PENDING", "PREPARING"]),
            )
            .values(status="FAILED", last_error="Permissão para destino externo revogada")
        )
    db.commit()
    return {"updated": True}


@router.delete("/users/{user_id}")
def delete_user(user_id: int, user: CurrentUser = Depends(require_user), db: Session = Depends(get_db)):
    _require_admin(db, user, lock=True)
    target = db.scalar(select(DashboardUser).where(DashboardUser.id == user_id).with_for_update())
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conta não encontrada")
    if target.id == user.id:
        raise HTTPException(status.HTTP_409_CONFLICT, "Você não pode excluir a própria conta")
    if target.is_admin and target.active:
        admin_count = db.scalar(
            select(func.count()).select_from(DashboardUser).where(
                DashboardUser.is_admin.is_(True), DashboardUser.active.is_(True)
            )
        ) or 0
        if admin_count <= 1:
            raise HTTPException(status.HTTP_409_CONFLICT, "O último administrador não pode ser excluído")
    preparing = db.scalar(
        select(func.count()).select_from(EmailSchedule).where(
            EmailSchedule.user_id == user_id, EmailSchedule.status == "PREPARING"
        )
    ) or 0
    if preparing:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Aguarde o envio de e-mail em preparação antes de excluir esta conta",
        )
    db.delete(target)
    db.commit()
    return {"deleted": True}
