"""Login protection: one admin user, scrypt password hash, signed session cookie.

First run: the app shows a "Create your login" page (like Radarr/Sonarr) and stores a
scrypt hash plus a generated session secret in data/auth.json (mode 0600). Until setup
is done nothing else is served. To reset, delete data/auth.json and restart.

Optional environment:
  SETUP_TOKEN           if set, the setup page also asks for it (closes the first-visit race)
  ADMIN_USERNAME / ADMIN_PASSWORD_HASH / SESSION_SECRET
                        override the file (hash from `python -m app.auth hash`)
  SESSION_HOURS         session lifetime (default 12)
  COOKIE_SECURE         "1" when served over HTTPS
  API_TOKEN             sent as `X-Api-Key` for scripts

Never falls back to "no auth".
Stdlib only (hashlib.scrypt, hmac) so there is no new dependency.
"""
from __future__ import annotations

import base64
import getpass
import hashlib
import hmac
import json
import os
import secrets
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

COOKIE = "shipyard_session"
# Reachable without a session. Everything else (including /docs, /openapi.json) is protected.
PUBLIC_PATHS = {"/login", "/logout", "/healthz", "/setup"}
PUBLIC_PREFIXES = ("/static/login",)

_N, _R, _P = 2**15, 8, 1


# ---- password hashing -------------------------------------------------------
def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, maxmem=64 * 1024 * 1024, dklen=32)
    return "scrypt$%d$%d$%d$%s$%s" % (
        _N, _R, _P, base64.b64encode(salt).decode(), base64.b64encode(dk).decode())


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, dk = stored.split("$")
        if scheme != "scrypt":
            return False
        got = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r),
                             p=int(p), maxmem=64 * 1024 * 1024, dklen=32)
        return hmac.compare_digest(got, base64.b64decode(dk))
    except Exception:
        return False


# ---- config -----------------------------------------------------------------
class Config:
    """Credentials, loaded from env (override) or data/auth.json (written by first-run setup).

    `configured` is False until setup is done; the middleware then only serves /setup.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self.api_token = os.environ.get("API_TOKEN", "").strip()
        self.setup_token = os.environ.get("SETUP_TOKEN", "").strip()
        self.cookie_secure = os.environ.get("COOKIE_SECURE", "") == "1"
        try:
            self.ttl = int(float(os.environ.get("SESSION_HOURS", "12")) * 3600)
        except ValueError:
            self.ttl = 12 * 3600
        if self.api_token and len(self.api_token) < 24:
            raise RuntimeError("API_TOKEN, if set, must be at least 24 characters.")
        self.username = self.pw_hash = self.secret = ""
        self.load()

    @property
    def configured(self) -> bool:
        return bool(self.pw_hash and self.secret)

    def load(self) -> None:
        env_hash = os.environ.get("ADMIN_PASSWORD_HASH", "").strip()
        env_secret = os.environ.get("SESSION_SECRET", "").strip()
        if env_hash or env_secret:  # explicit override; must be complete and valid
            if not env_hash.startswith("scrypt$") or len(env_secret) < 32:
                raise RuntimeError("ADMIN_PASSWORD_HASH / SESSION_SECRET are set but invalid "
                                   "(hash must start with scrypt$, secret >= 32 chars).")
            self.username = os.environ.get("ADMIN_USERNAME", "admin")
            self.pw_hash, self.secret = env_hash, env_secret
            return
        if self.path.exists():
            data = json.loads(self.path.read_text())
            self.username, self.pw_hash, self.secret = data["username"], data["hash"], data["secret"]
            if not self.configured or len(self.secret) < 32:
                raise RuntimeError(f"{self.path} is incomplete; delete it to run setup again.")

    def create(self, username: str, password: str) -> None:
        """First-run setup. Refuses if already configured."""
        if self.configured:
            raise RuntimeError("already configured")
        data = {"username": username, "hash": hash_password(password),
                "secret": secrets.token_urlsafe(48)}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as fh:
            json.dump(data, fh)
        os.replace(tmp, self.path)
        self.username, self.pw_hash, self.secret = data["username"], data["hash"], data["secret"]


# ---- session cookie ---------------------------------------------------------
def _sign(secret: str, payload: str) -> str:
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


def make_session(cfg: Config) -> str:
    payload = base64.urlsafe_b64encode(json.dumps(
        {"u": cfg.username, "exp": int(time.time()) + cfg.ttl}).encode()).decode()
    return payload + "." + _sign(cfg.secret, payload)


def read_session(cfg: Config, token: str | None) -> bool:
    if not token or "." not in token:
        return False
    payload, sig = token.rsplit(".", 1)
    if not hmac.compare_digest(sig, _sign(cfg.secret, payload)):
        return False
    try:
        data = json.loads(base64.urlsafe_b64decode(payload.encode()))
        return data["u"] == cfg.username and data["exp"] > time.time()
    except Exception:
        return False


def api_token_ok(cfg: Config, header: str | None) -> bool:
    return bool(cfg.api_token and header and hmac.compare_digest(header, cfg.api_token))


def origin_ok(origin: str | None, host: str | None) -> bool:
    """CSRF guard for state-changing requests: if a browser sent Origin, it must match Host."""
    if not origin:
        return True
    return urlsplit(origin).netloc == (host or "")


# ---- login throttling -------------------------------------------------------
class Throttle:
    """Per-client failure counter. After 5 failures, each further attempt waits 2^n seconds (max 15 min)."""

    def __init__(self) -> None:
        self._fails: dict[str, tuple[int, float]] = {}

    def wait(self, key: str) -> int:
        n, last = self._fails.get(key, (0, 0.0))
        if n < 5:
            return 0
        return max(0, int(last + min(2 ** (n - 4), 900) - time.time()))

    def fail(self, key: str) -> None:
        n, _ = self._fails.get(key, (0, 0.0))
        if len(self._fails) > 1000:
            self._fails.clear()
        self._fails[key] = (n + 1, time.time())

    def ok(self, key: str) -> None:
        self._fails.pop(key, None)


# ---- CLI helper -------------------------------------------------------------
if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "hash":
        pw = getpass.getpass("Password: ")
        if len(pw) < 10:
            sys.exit("Use at least 10 characters.")
        if pw != getpass.getpass("Repeat: "):
            sys.exit("Passwords differ.")
        print(hash_password(pw))
    elif cmd == "secret":
        print(secrets.token_urlsafe(48))
    else:
        sys.exit("usage: python -m app.auth hash|secret")
