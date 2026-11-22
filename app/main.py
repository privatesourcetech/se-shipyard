from pathlib import Path

import logging
from html import escape

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app import auth
from app.instances import DATA_DIR
from app.routes import api

log = logging.getLogger("uvicorn.error")
cfg = auth.Config(DATA_DIR / "auth.json")  # not configured -> only /setup is served
throttle = auth.Throttle()

STATIC_DIR = Path(__file__).parent / "static"


class RevalidatingStaticFiles(StaticFiles):
    """Always revalidate (ETag -> 304), so a redeploy is never masked by a stale browser cache."""

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response


# No /docs, /redoc or /openapi.json: they would list every route.
app = FastAPI(title="SE Shipyard", docs_url=None, redoc_url=None, openapi_url=None)


@app.middleware("http")
async def require_login(request: Request, call_next):
    path = request.url.path
    if path in auth.PUBLIC_PATHS or path.startswith(auth.PUBLIC_PREFIXES):
        return await call_next(request)
    if not cfg.configured:  # first run: nothing is served until the admin login exists
        if path.startswith("/api/"):
            return JSONResponse({"detail": "Setup required"}, status_code=401)
        return RedirectResponse("/setup", status_code=303)
    token_ok = auth.api_token_ok(cfg, request.headers.get("x-api-key"))
    session_ok = auth.read_session(cfg, request.cookies.get(auth.COOKIE))
    if not (token_ok or session_ok):
        if path.startswith("/api/"):
            return JSONResponse({"detail": "Not signed in"}, status_code=401)
        return RedirectResponse("/login", status_code=303)
    if (request.method not in ("GET", "HEAD", "OPTIONS") and not token_ok
            and not auth.origin_ok(request.headers.get("origin"), request.headers.get("host"))):
        return JSONResponse({"detail": "Cross-origin request refused"}, status_code=403)
    return await call_next(request)


app.include_router(api.router)
app.mount("/static", RevalidatingStaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", include_in_schema=False)
def index():
    # Version the script URL by file mtime so a changed app.js is always refetched.
    version = int((STATIC_DIR / "app.js").stat().st_mtime)
    html = (STATIC_DIR / "index.html").read_text().replace("__V__", str(version))
    return HTMLResponse(html, headers={"Cache-Control": "no-cache"})


@app.get("/healthz", include_in_schema=False)
def healthz():
    return {"ok": True}


_LOGIN_HTML = """<!doctype html><html lang="en" data-theme="dark"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>SE Shipyard - Sign in</title>
<style>
body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;background:#0f1319;
color:#e6ebf3;font:14px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
form{background:#171d26;border:1px solid #2b3545;border-radius:10px;padding:28px;width:300px;
box-shadow:0 1px 3px rgba(0,0,0,.5)}
h1{font-size:17px;margin:0 0 18px}label{display:block;font-size:12px;color:#8c99ad;margin-bottom:12px}
input{display:block;width:100%;box-sizing:border-box;margin-top:4px;background:#0f1319;border:1px solid #2b3545;
border-radius:6px;padding:8px;color:#e6ebf3;font:inherit}
input:focus{outline:2px solid #4c8dff;outline-offset:-1px}
button{width:100%;margin-top:6px;background:#4c8dff;color:#06101f;border:0;border-radius:6px;padding:9px;
font:inherit;font-weight:600;cursor:pointer}
.err{color:#ff6b63;margin:0 0 12px;font-size:13px}
</style></head><body><form method="post" action="__ACTION__">
<h1>SE Shipyard</h1>__ERR__
__FIELDS__
<button type="submit">__BTN__</button></form></body></html>"""

_SIGNIN_FIELDS = """<label>Username<input name="username" autocomplete="username" autofocus required></label>
<label>Password<input name="password" type="password" autocomplete="current-password" required></label>"""

_SETUP_FIELDS = """<p style="color:#8c99ad;margin:0 0 14px">First run: create your login.</p>
<label>Username<input name="username" value="admin" autocomplete="username" required></label>
<label>Password (10+ characters)<input name="password" type="password" autocomplete="new-password" minlength="10" required autofocus></label>
<label>Repeat password<input name="password2" type="password" autocomplete="new-password" minlength="10" required></label>
__TOKEN__"""


def _page(fields: str, button: str, action: str, error: str = "", status: int = 200) -> HTMLResponse:
    err = f'<p class="err">{escape(error)}</p>' if error else ""
    html = _LOGIN_HTML.replace("__FIELDS__", fields).replace("__BTN__", button).replace("__ACTION__", action).replace("__ERR__", err)
    return HTMLResponse(html, status_code=status, headers={"Cache-Control": "no-store"})


def _login_page(error: str = "", status: int = 200) -> HTMLResponse:
    return _page(_SIGNIN_FIELDS, "Sign in", "/login", error, status)


def _setup_page(error: str = "", status: int = 200) -> HTMLResponse:
    token = ('<label>Setup token<input name="token" type="password" required></label>'
             if cfg.setup_token else "")
    return _page(_SETUP_FIELDS.replace("__TOKEN__", token), "Create login", "/setup", error, status)


def _form(body: bytes) -> dict[str, str]:
    from urllib.parse import parse_qs  # tiny urlencoded form: no python-multipart dependency
    return {k: v[0] for k, v in parse_qs(body.decode("utf-8", "replace")).items()}


@app.get("/setup", include_in_schema=False)
def setup_form():
    if cfg.configured:
        return RedirectResponse("/login", status_code=303)
    return _setup_page()


@app.post("/setup", include_in_schema=False)
async def setup(request: Request):
    if cfg.configured:  # setup can never be re-run or used to overwrite the login
        return RedirectResponse("/login", status_code=303)
    if not auth.origin_ok(request.headers.get("origin"), request.headers.get("host")):
        return _setup_page("Cross-origin request refused.", 403)
    client = request.client.host if request.client else "?"
    wait = throttle.wait(client)
    if wait:
        return _setup_page(f"Too many failed attempts. Try again in {wait}s.", 429)
    f = _form(await request.body())
    user, pw = f.get("username", "").strip(), f.get("password", "")
    if cfg.setup_token and not auth.hmac.compare_digest(f.get("token", "").encode(), cfg.setup_token.encode()):
        throttle.fail(client)
        return _setup_page("Wrong setup token.", 401)
    if not user or len(user) > 64:
        return _setup_page("Enter a username (up to 64 characters).", 400)
    if len(pw) < 10:
        return _setup_page("Password must be at least 10 characters.", 400)
    if pw != f.get("password2", ""):
        return _setup_page("Passwords do not match.", 400)
    cfg.create(user, pw)
    log.warning("Admin login created via setup page (from %s)", client)
    resp = RedirectResponse("/", status_code=303)
    resp.set_cookie(auth.COOKIE, auth.make_session(cfg), max_age=cfg.ttl, httponly=True,
                    samesite="strict", secure=cfg.cookie_secure, path="/")
    return resp


@app.get("/login", include_in_schema=False)
def login_form(request: Request):
    if not cfg.configured:
        return RedirectResponse("/setup", status_code=303)
    if auth.read_session(cfg, request.cookies.get(auth.COOKIE)):
        return RedirectResponse("/", status_code=303)
    return _login_page()


@app.post("/login", include_in_schema=False)
async def login(request: Request):
    if not cfg.configured:
        return RedirectResponse("/setup", status_code=303)
    if not auth.origin_ok(request.headers.get("origin"), request.headers.get("host")):
        return _login_page("Cross-origin request refused.", 403)
    client = request.client.host if request.client else "?"
    wait = throttle.wait(client)
    if wait:
        return _login_page(f"Too many failed attempts. Try again in {wait}s.", 429)
    form = _form(await request.body())
    user, password = form.get("username", ""), form.get("password", "")
    # Always run the hash check so timing doesn't reveal a valid username.
    pw_ok = auth.verify_password(password, cfg.pw_hash)
    user_ok = auth.hmac.compare_digest(user.encode(), cfg.username.encode())
    if not (pw_ok and user_ok):
        throttle.fail(client)
        log.warning("Failed login from %s", client)
        return _login_page("Wrong username or password.", 401)
    throttle.ok(client)
    resp = RedirectResponse("/", status_code=303)
    resp.set_cookie(auth.COOKIE, auth.make_session(cfg), max_age=cfg.ttl, httponly=True,
                    samesite="strict", secure=cfg.cookie_secure, path="/")
    return resp


@app.post("/logout", include_in_schema=False)
def logout():
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie(auth.COOKIE, path="/")
    return resp
