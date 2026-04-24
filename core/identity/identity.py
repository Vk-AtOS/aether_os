# aetherone/identity.py
from __future__ import annotations
import os
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import (Column, Integer, String, DateTime, Boolean, Table, MetaData, create_engine)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql import select
from sqlalchemy.orm import sessionmaker
from passlib.context import CryptContext
from jose import jwt, JWTError

# Config
DB_DIR = os.path.expanduser(".aether-one")
os.makedirs(DB_DIR, exist_ok=True)
DB_PATH = os.path.join(DB_DIR, "identity.db")
SQLALCHEMY_DATABASE_URL = f"sqlite+aiosqlite:///{DB_PATH}"

SECRET_KEY = os.environ.get("AETHERONE_JWT_SECRET", "dev-secret-use-secure-in-prod")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # default 1 week

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
metadata = MetaData()

users = Table(
    "users",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("username", String(128), unique=True, nullable=False),
    Column("full_name", String(256), nullable=True),
    Column("email", String(256), nullable=True),
    Column("hashed_password", String(512), nullable=False),
    Column("roles", String(256), nullable=True),  # comma-separated roles
    Column("is_active", Boolean, default=True),
    Column("created_at", DateTime, default=datetime.utcnow),
)

engine = create_engine(SQLALCHEMY_DATABASE_URL, future=True, echo=False)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, future=True)

def init_db():
    metadata.create_all(engine)

def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)

def create_user(username: str, password: str, email: Optional[str] = None, full_name: Optional[str] = None, roles: Optional[list[str]] = None) -> dict:
    init_db()
    roles_csv = ",".join(roles or [])
    hashed = get_password_hash(password)
    with engine.begin() as conn:
        try:
            res = conn.execute(users.insert().values(
                username=username,
                full_name=full_name,
                email=email,
                hashed_password=hashed,
                roles=roles_csv,
                is_active=True,
                created_at=datetime.utcnow(),
            ))
            uid = res.inserted_primary_key[0]
            return {"id": uid, "username": username, "roles": roles or []}
        except IntegrityError:
            raise ValueError("username already exists")

def authenticate_user(username: str, password: str) -> Optional[dict]:
    init_db()
    with engine.connect() as conn:
        row = conn.execute(select(users).where(users.c.username == username)).first()
        if not row:
            return None
        user = dict(row)
        if not verify_password(password, user["hashed_password"]):
            return None
        # parse roles
        roles = (user.get("roles") or "").split(",") if user.get("roles") else []
        return {"id": user["id"], "username": user["username"], "roles": roles, "email": user.get("email")}

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def decode_access_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError as exc:
        raise ValueError("Invalid token") from exc

def get_user_by_username(username: str) -> Optional[dict]:
    init_db()
    with engine.connect() as conn:
        row = conn.execute(select(users).where(users.c.username == username)).first()
        return dict(row) if row else None

# simple helper to check role membership
def user_has_role(user: dict, role: str) -> bool:
    if not user:
        return False
    roles = user.get("roles") or ""
    return role in (roles.split(",") if roles else [])

