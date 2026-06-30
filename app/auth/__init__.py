__all__ = ["user_store"]


def __getattr__(name: str):
    if name == "user_store":
        from app.auth.store import user_store

        return user_store
    raise AttributeError(name)
