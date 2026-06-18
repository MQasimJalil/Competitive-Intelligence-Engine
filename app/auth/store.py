from pathlib import Path
from threading import Lock
from typing import Protocol

from app.auth.security import hash_password
from app.config import settings
from app.schemas.auth import AppUser, UserRole, UserSummary, summarize_user


class UserRepository(Protocol):
    def create_user(
        self,
        *,
        name: str,
        email: str,
        password: str,
        role: UserRole = "tester",
    ) -> AppUser: ...
    def get(self, user_id: str) -> AppUser | None: ...
    def get_by_email(self, email: str) -> AppUser | None: ...
    def list_users(self) -> list[UserSummary]: ...
    def count_users(self) -> int: ...


class FileUserStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self._lock = Lock()

    def create_user(
        self,
        *,
        name: str,
        email: str,
        password: str,
        role: UserRole = "tester",
    ) -> AppUser:
        if self.get_by_email(email):
            raise ValueError("User already exists for this email")
        user = AppUser(
            name=name,
            email=email,
            password_hash=hash_password(password),
            role=role,
        )
        self.save(user)
        return user

    def get(self, user_id: str) -> AppUser | None:
        path = self._path(user_id)
        if not path.exists():
            return None
        return AppUser.model_validate_json(path.read_text(encoding="utf-8"))

    def get_by_email(self, email: str) -> AppUser | None:
        normalized = _normalize_email(email)
        for user in self._all_users():
            if user.email == normalized:
                return user
        return None

    def list_users(self) -> list[UserSummary]:
        return [
            summarize_user(user)
            for user in sorted(self._all_users(), key=lambda item: item.created_at)
        ]

    def count_users(self) -> int:
        return len(self._all_users())

    def save(self, user: AppUser) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        path = self._path(user.user_id)
        temporary = path.with_suffix(".tmp")
        with self._lock:
            temporary.write_text(user.model_dump_json(indent=2), encoding="utf-8")
            temporary.replace(path)

    def _all_users(self) -> list[AppUser]:
        if not self.root.exists():
            return []
        users = []
        for path in self.root.glob("*.json"):
            try:
                users.append(AppUser.model_validate_json(path.read_text(encoding="utf-8")))
            except ValueError:
                continue
        return users

    def _path(self, user_id: str) -> Path:
        return self.root / f"{_safe_id(user_id)}.json"


class PostgresUserStore:
    def __init__(self, database_url: str):
        if not database_url:
            raise ValueError("DATABASE_URL is required for the Postgres user repository")
        self.database_url = database_url
        self.initialize()

    def _connect(self):
        import psycopg

        return psycopg.connect(self.database_url)

    def initialize(self) -> None:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS app_users (
                    user_id TEXT PRIMARY KEY,
                    email TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    role TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL,
                    payload JSONB NOT NULL
                );
                CREATE INDEX IF NOT EXISTS app_users_created_idx
                    ON app_users (created_at);
                """
            )

    def create_user(
        self,
        *,
        name: str,
        email: str,
        password: str,
        role: UserRole = "tester",
    ) -> AppUser:
        if self.get_by_email(email):
            raise ValueError("User already exists for this email")
        user = AppUser(
            name=name,
            email=email,
            password_hash=hash_password(password),
            role=role,
        )
        self.save(user)
        return user

    def get(self, user_id: str) -> AppUser | None:
        row = self._fetchone("SELECT payload FROM app_users WHERE user_id = %s", (user_id,))
        return AppUser.model_validate(row[0]) if row else None

    def get_by_email(self, email: str) -> AppUser | None:
        row = self._fetchone(
            "SELECT payload FROM app_users WHERE email = %s",
            (_normalize_email(email),),
        )
        return AppUser.model_validate(row[0]) if row else None

    def list_users(self) -> list[UserSummary]:
        rows = self._fetchall("SELECT payload FROM app_users ORDER BY created_at", ())
        return [summarize_user(AppUser.model_validate(row[0])) for row in rows]

    def count_users(self) -> int:
        row = self._fetchone("SELECT COUNT(*) FROM app_users", ())
        return int(row[0]) if row else 0

    def save(self, user: AppUser) -> None:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO app_users (user_id, email, name, role, created_at, payload)
                VALUES (%s, %s, %s, %s, %s, %s::jsonb)
                ON CONFLICT (user_id) DO UPDATE SET
                    email = EXCLUDED.email,
                    name = EXCLUDED.name,
                    role = EXCLUDED.role,
                    payload = EXCLUDED.payload
                """,
                (
                    user.user_id,
                    user.email,
                    user.name,
                    user.role,
                    user.created_at,
                    user.model_dump_json(),
                ),
            )

    def _fetchone(self, query: str, values: tuple):
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(query, values)
            return cursor.fetchone()

    def _fetchall(self, query: str, values: tuple):
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(query, values)
            return cursor.fetchall()


def build_user_store(repository: str, *, root: str | Path, database_url: str):
    if repository.casefold() == "postgres":
        return PostgresUserStore(database_url)
    return FileUserStore(root)


def ensure_seed_admin(store: UserRepository) -> None:
    if store.count_users() > 0:
        return
    if not settings.admin_email or not settings.admin_password:
        return
    store.create_user(
        name=settings.admin_name,
        email=settings.admin_email,
        password=settings.admin_password,
        role="admin",
    )


def _normalize_email(email: str) -> str:
    return email.strip().casefold()


def _safe_id(value: str) -> str:
    return "".join(character for character in value if character.isalnum())


user_store = build_user_store(
    settings.user_repository,
    root=settings.user_store_dir,
    database_url=settings.database_url,
)
ensure_seed_admin(user_store)
