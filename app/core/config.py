"""Application configuration loaded from environment variables."""

from os import getenv
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy.engine import make_url


PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

DEBUG = getenv("DEBUG", "false").lower() in {"1", "true", "yes", "on"}
JWT_SECRET_KEY = getenv("JWT_SECRET_KEY", "")
ACCESS_TOKEN_EXPIRE_MINUTES = int(getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "10080"))

AUTH_COOKIE_NAME = getenv("AUTH_COOKIE_NAME", "tophoo_global_access_token")
AUTH_COOKIE_SECURE = getenv("AUTH_COOKIE_SECURE", "true" if not DEBUG else "false").lower() in {"1", "true", "yes", "on"}
# Never let a fake checkout grant paid access on a production deployment.
TEST_CHECKOUT_ENABLED = DEBUG and getenv("TEST_CHECKOUT_ENABLED", "false").lower() in {"1", "true", "yes", "on"}


def validate_jwt_secret():
    if len(JWT_SECRET_KEY.encode("utf-8")) < 32 or JWT_SECRET_KEY in {
        "change-this-secret-before-production", "replace-with-a-long-random-secret",
    }:
        raise RuntimeError("请设置至少 32 字节的随机 JWT_SECRET_KEY，再启动应用。")

def database_url():
    url = make_url(getenv("DATABASE_URL") or "sqlite:///data/tophoo_global.sqlite3")
    if url.get_backend_name() == "sqlite" and url.database not in (None, "", ":memory:") and not url.query.get("uri"):
        path = PROJECT_ROOT / url.database
        if path.parent == PROJECT_ROOT / "data":
            path.parent.mkdir(exist_ok=True)
        url = url.set(database=str(path))
    return url.render_as_string(hide_password=False)


DATABASE_URL = database_url()
