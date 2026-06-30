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
        supabase_user_id: str = "",
        phone_number: str = "",
        credit_balance: int = 0,
        is_active: bool = True,
    ) -> AppUser: ...
    def get(self, user_id: str) -> AppUser | None: ...
    def get_by_supabase_user_id(self, supabase_user_id: str) -> AppUser | None: ...
    def get_by_email(self, email: str) -> AppUser | None: ...
    def list_users(self) -> list[UserSummary]: ...
    def count_users(self) -> int: ...
    def save(self, user: AppUser) -> None: ...


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
        supabase_user_id: str = "",
        phone_number: str = "",
        credit_balance: int = 0,
        is_active: bool = True,
    ) -> AppUser:
        if self.get_by_email(email):
            raise ValueError("User already exists for this email")
        user = AppUser(
            name=name,
            email=email,
            password_hash=hash_password(password),
            role=role,
            supabase_user_id=supabase_user_id,
            phone_number=phone_number,
            credit_balance=credit_balance,
            is_active=is_active,
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

    def get_by_supabase_user_id(self, supabase_user_id: str) -> AppUser | None:
        if not supabase_user_id:
            return None
        for user in self._all_users():
            if user.supabase_user_id == supabase_user_id:
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
                    supabase_user_id TEXT,
                    email TEXT NOT NULL UNIQUE,
                    phone_number TEXT NOT NULL DEFAULT '',
                    name TEXT NOT NULL,
                    role TEXT NOT NULL,
                    credit_balance INTEGER NOT NULL DEFAULT 0,
                    is_active BOOLEAN NOT NULL DEFAULT TRUE,
                    created_at TIMESTAMPTZ NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL,
                    payload JSONB NOT NULL
                );
                CREATE INDEX IF NOT EXISTS app_users_created_idx
                    ON app_users (created_at);
                """
            )
            cursor.execute("ALTER TABLE app_users ADD COLUMN IF NOT EXISTS supabase_user_id TEXT")
            cursor.execute(
                """
                ALTER TABLE app_users
                ADD COLUMN IF NOT EXISTS phone_number TEXT NOT NULL DEFAULT ''
                """
            )
            cursor.execute(
                """
                ALTER TABLE app_users
                ADD COLUMN IF NOT EXISTS credit_balance INTEGER NOT NULL DEFAULT 0
                """
            )
            cursor.execute(
                """
                ALTER TABLE app_users
                ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE
                """
            )
            cursor.execute(
                "ALTER TABLE app_users ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ"
            )
            cursor.execute(
                "UPDATE app_users SET updated_at = created_at WHERE updated_at IS NULL"
            )
            cursor.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS app_users_supabase_user_id_idx
                    ON app_users (supabase_user_id)
                    WHERE supabase_user_id IS NOT NULL AND supabase_user_id <> ''
                """
            )

    def create_user(
        self,
        *,
        name: str,
        email: str,
        password: str,
        role: UserRole = "tester",
        supabase_user_id: str = "",
        phone_number: str = "",
        credit_balance: int = 0,
        is_active: bool = True,
    ) -> AppUser:
        if self.get_by_email(email):
            raise ValueError("User already exists for this email")
        user = AppUser(
            name=name,
            email=email,
            password_hash=hash_password(password),
            role=role,
            supabase_user_id=supabase_user_id,
            phone_number=phone_number,
            credit_balance=credit_balance,
            is_active=is_active,
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

    def get_by_supabase_user_id(self, supabase_user_id: str) -> AppUser | None:
        if not supabase_user_id:
            return None
        row = self._fetchone(
            "SELECT payload FROM app_users WHERE supabase_user_id = %s",
            (supabase_user_id,),
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
                INSERT INTO app_users (
                    user_id,
                    supabase_user_id,
                    email,
                    phone_number,
                    name,
                    role,
                    credit_balance,
                    is_active,
                    created_at,
                    updated_at,
                    payload
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                ON CONFLICT (user_id) DO UPDATE SET
                    supabase_user_id = EXCLUDED.supabase_user_id,
                    email = EXCLUDED.email,
                    phone_number = EXCLUDED.phone_number,
                    name = EXCLUDED.name,
                    role = EXCLUDED.role,
                    credit_balance = EXCLUDED.credit_balance,
                    is_active = EXCLUDED.is_active,
                    updated_at = EXCLUDED.updated_at,
                    payload = EXCLUDED.payload
                """,
                (
                    user.user_id,
                    user.supabase_user_id or None,
                    user.email,
                    user.phone_number,
                    user.name,
                    user.role,
                    user.credit_balance,
                    user.is_active,
                    user.created_at,
                    user.updated_at,
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
    if settings.auth_provider == "supabase":
        from app.auth.supabase_store import SupabaseAuthClient, SupabaseUserStore
        from app.credits import credit_store

        metadata_database_url = settings.supabase_db_url or database_url
        metadata_store = (
            PostgresUserStore(metadata_database_url)
            if repository.casefold() == "postgres"
            else FileUserStore(root)
        )
        auth_client = SupabaseAuthClient(
            url=settings.supabase_url,
            anon_key=settings.supabase_anon_key,
            service_role_key=settings.supabase_service_role_key,
        )
        return SupabaseUserStore(metadata_store, auth_client, credit_store=credit_store)
    if repository.casefold() == "postgres":
        return PostgresUserStore(database_url)
    return FileUserStore(root)


def ensure_seed_admin(store: UserRepository) -> None:
    try:
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
    except Exception as exc:
        import logging
        logging.warning("Could not ensure seed admin user: %s", exc)


class LazyUserStore:
    def __init__(self):
        self._store = None
        self._lock = Lock()

    def _get_store(self):
        if self._store is None:
            with self._lock:
                if self._store is None:
                    store = build_user_store(
                        settings.user_repository,
                        root=settings.user_store_dir,
                        database_url=settings.database_url,
                    )
                    ensure_seed_admin(store)
                    self._store = store
        return self._store

    def __getattr__(self, name: str):
        return getattr(self._get_store(), name)


def _normalize_email(email: str) -> str:
    return email.strip().casefold()


def _safe_id(value: str) -> str:
    return "".join(character for character in value if character.isalnum())


user_store = LazyUserStore()
