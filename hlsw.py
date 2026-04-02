#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.12"
# dependencies = ["requests", "click"]
# ///
"""hiLife Sound Wave Utility - Generate unlock sound waves for hiLife smart community doors."""

import json
import os
import sys
import time
import uuid
from datetime import datetime

import click
import requests

# API endpoints
HILIFE_API = "https://api3.hilife.sg"
XINGWANG_API = "http://sopen.hilife.sg:8888"

# XingWang credentials (extracted from APK)
XW_CLIENT_ID = "0200101001"
XW_CLIENT_SECRET = "96BB44D74D9FA5A603FB92A8F713DD802A127C17"

APP_NAME = "hlsw"


def _get_cache_dir() -> str:
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA", os.path.expanduser("~/AppData/Local"))
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Caches")
    else:
        base = os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache"))
    return os.path.join(base, APP_NAME)


CACHE_DIR = _get_cache_dir()
LOGIN_CACHE = os.path.join(CACHE_DIR, "login.json")
XW_AUTH_CACHE = os.path.join(CACHE_DIR, "xw_auth.json")


def log(msg: str):
    click.echo(msg, err=True)


def die(msg: str):
    click.echo(msg, err=True)
    sys.exit(1)


# ---- Cache helpers ----

def load_json_cache(path: str) -> dict | None:
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return None


def save_json_cache(path: str, data: dict):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


# ---- hiLife API ----

def hilife_login(account: str, password: str) -> dict:
    resp = requests.post(f"{HILIFE_API}/v3/app/login", json={
        "account": account,
        "password": password,
        "device_type": "Android",
        "device_token": "",
        "voip_token": "",
    })
    log(f"[hiLife login] status={resp.status_code}")
    data = resp.json()
    log(json.dumps(data, indent=2))
    return data


def extract_user_id(login_data: dict) -> str | None:
    return (
        login_data.get("userId")
        or login_data.get("user_id")
        or login_data.get("data", {}).get("userId")
        or login_data.get("data", {}).get("user_id")
    )


# ---- XingWang API ----

def xw_auth(user_id: str) -> str:
    cached = load_json_cache(XW_AUTH_CACHE)
    if cached and cached.get("expires_at", 0) > time.time():
        log("[*] Using cached XW token")
        return cached["access_token"]

    resp = requests.post(f"{XINGWANG_API}/V1.0/users/access_token", json={
        "grant_type": "client_credentials",
        "client_id": XW_CLIENT_ID,
        "client_secret": XW_CLIENT_SECRET,
        "uuid": uuid.uuid4().hex[:16],
        "user_id": user_id,
        "type": 0,
    })
    log(f"[XW auth] status={resp.status_code}")
    data = resp.json()
    if data.get("access_token"):
        data["expires_at"] = time.time() + data.get("expires_in", 0) - 60
        save_json_cache(XW_AUTH_CACHE, data)
    return data.get("access_token")


def xw_get_apartments(token: str) -> list:
    resp = requests.get(f"{XINGWANG_API}/V1.0/apartments",
                        params={"access_token": token, "cursor": 0})
    return resp.json().get("list", [])


def xw_get_or_create_wave(token: str, apartment_id: str, wave_type: int = 0) -> dict | None:
    resp = requests.get(
        f"{XINGWANG_API}/V1.0/apartments/{apartment_id}/unlocks/waves",
        params={"access_token": token, "type": wave_type, "page": 0, "size": 1},
    )
    waves = resp.json().get("list", [])
    if waves:
        return waves[0]

    log("[*] No existing wave, creating one...")
    resp = requests.post(
        f"{XINGWANG_API}/V1.0/apartments/{apartment_id}/unlocks/waves",
        params={"access_token": token},
        json={"type": wave_type},
    )
    return resp.json()


def xw_create_visitor_wave(token: str, apartment_id: str,
                           effect_time: int, expired_time: int,
                           count: int = 1, remark: str = "") -> dict:
    body = {"type": 1, "effect_time": effect_time, "expired_time": expired_time, "count": count}
    if remark:
        body["remark"] = remark
    resp = requests.post(
        f"{XINGWANG_API}/V1.0/apartments/{apartment_id}/unlocks/waves",
        params={"access_token": token},
        json=body,
    )
    return resp.json()


def xw_list_visitor_waves(token: str, apartment_id: str) -> list:
    resp = requests.get(
        f"{XINGWANG_API}/V1.0/apartments/{apartment_id}/unlocks/waves",
        params={"access_token": token, "type": 1, "page": 0, "size": 50},
    )
    return resp.json().get("list", [])


def xw_delete_wave(token: str, apartment_id: str, wave_id: int):
    resp = requests.delete(
        f"{XINGWANG_API}/V1.0/apartments/{apartment_id}/unlocks/waves/{wave_id}",
        params={"access_token": token},
    )
    log(f"[*] Deleted wave {wave_id} (status={resp.status_code})")


# ---- Helpers ----

def download_audio(url: str, output_path: str) -> str:
    dirname = os.path.dirname(output_path)
    if dirname:
        os.makedirs(dirname, exist_ok=True)
    resp = requests.get(url)
    resp.raise_for_status()
    with open(output_path, "wb") as f:
        f.write(resp.content)
    return output_path


def parse_duration(s: str) -> int:
    s = s.strip().lower()
    multipliers = {"m": 60, "h": 3600, "d": 86400}
    if s[-1] in multipliers:
        return int(s[:-1]) * multipliers[s[-1]]
    return int(s)


def ensure_auth() -> tuple[str, str]:
    """Returns (xw_token, apartment_id)."""
    login_data = load_json_cache(LOGIN_CACHE)
    if not login_data:
        die("[!] No cached login. Run 'hlsw.py auth' first.")
    log("[*] Using cached login")

    user_id = extract_user_id(login_data)
    if not user_id:
        die("[!] Could not extract userId.")
    log(f"[*] userId: {user_id}")

    xw_token = xw_auth(str(user_id))
    if not xw_token:
        die("[!] Failed to get XW token.")

    apartments = xw_get_apartments(xw_token)
    if not apartments:
        die("[!] No apartments found.")

    apt = apartments[0]
    log(f"[*] Apartment: {apt['name']} (id={apt['id']})")
    return xw_token, apt["id"]


def resolve_output(output: str | None, default_name: str) -> str:
    return output or default_name


# ---- CLI ----

@click.group()
def cli():
    """hiLife Sound Wave Utility"""


@cli.command()
@click.option("--account", required=True, help="hiLife account (mobile or email)")
@click.option("--password", required=True, help="hiLife account password")
def auth(account, password):
    """Login and cache credentials."""
    log("[*] Logging in to hiLife...")
    login_data = hilife_login(account, password)
    if login_data.get("code") != 200:
        die("[!] Login failed.")
    save_json_cache(LOGIN_CACHE, login_data)
    log(f"[*] Logged in as userId: {extract_user_id(login_data)}")


@cli.group()
def generate():
    """Generate unlock sound wave."""


@generate.command("owner")
@click.option("-o", "--output", type=click.Path(), default=None, help="Output file path")
def generate_owner(output):
    """Download owner unlock wave (permanent, unlimited use)."""
    xw_token, apartment_id = ensure_auth()

    wave = xw_get_or_create_wave(xw_token, apartment_id)
    if not wave:
        die("[!] Failed to get unlock wave.")

    audio_url = wave.get("audio_url")
    if not audio_url:
        die("[!] No audio_url in wave response.")

    log(f"[*] content={wave.get('content')} url={audio_url}")
    ext = os.path.splitext(audio_url)[-1] or ".mp3"
    path = resolve_output(output, f"unlock{ext}")
    download_audio(audio_url, path)
    click.echo(path)


@generate.command("visitor")
@click.option("-o", "--output", type=click.Path(), default=None, help="Output file path")
@click.option("--duration", default="24h", help="Validity duration (e.g. 1h, 30m, 2d). Default: 24h")
@click.option("--count", default=1, type=int, help="Number of allowed uses. Default: 1")
@click.option("--remark", default="", help="Optional description")
def generate_visitor(output, duration, count, remark):
    """Create a visitor wave (temporary, limited uses)."""
    xw_token, apartment_id = ensure_auth()

    now = int(time.time())
    expired = now + parse_duration(duration)

    wave = xw_create_visitor_wave(xw_token, apartment_id, now, expired, count, remark)
    if not wave.get("audio_url"):
        die("[!] Failed to create visitor wave.")

    log(f"[*] content={wave.get('content')} url={wave['audio_url']}")
    log(f"[*] valid: {datetime.fromtimestamp(now)} -> {datetime.fromtimestamp(expired)}, uses: {count}")

    ext = os.path.splitext(wave["audio_url"])[-1] or ".mp3"
    path = resolve_output(output, f"visitor_{wave['id']}{ext}")
    download_audio(wave["audio_url"], path)
    click.echo(path)


@cli.group()
def visitor():
    """Manage visitor waves."""


@visitor.command("list")
def visitor_list():
    """List all visitor waves."""
    xw_token, apartment_id = ensure_auth()
    waves = xw_list_visitor_waves(xw_token, apartment_id)

    if not waves:
        log("[*] No visitor waves.")
        return

    now = int(time.time())
    for w in waves:
        exp = w.get("expired_time", 0)
        status = "EXPIRED" if exp and exp < now else "ACTIVE"
        created = datetime.fromtimestamp(w["create_time"]).strftime("%Y-%m-%d %H:%M")
        exp_str = datetime.fromtimestamp(exp).strftime("%Y-%m-%d %H:%M") if exp else "never"
        click.echo(f"  [{status}] id={w['id']} content={w.get('content', '')} "
                    f"created={created} expires={exp_str} "
                    f"count={w.get('count', 0)} remark={w.get('remark', '')}")
        click.echo(f"           url={w.get('audio_url', '')}")


@visitor.command("delete")
@click.argument("wave_id", type=int)
def visitor_delete(wave_id):
    """Delete a visitor wave by ID."""
    xw_token, apartment_id = ensure_auth()
    xw_delete_wave(xw_token, apartment_id, wave_id)


if __name__ == "__main__":
    cli()
