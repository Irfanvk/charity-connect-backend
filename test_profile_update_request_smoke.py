#!/usr/bin/env python3
"""
Smoke test: member profile update request flow.

Flow covered:
1) Member login
2) Submit /requests/profile-update
3) Assert response includes profile-update metadata fields
4) Admin login
5) Approve request via /requests/{id}
6) Assert member notification is created
7) Assert audit log entry exists (profile_update_request_approved)

Usage:
  python test_profile_update_request_smoke.py

Optional environment variables:
  BASE_URL (default: http://127.0.0.1:8000)
  E2E_MEMBER_LOGIN
  E2E_MEMBER_PASSWORD
  E2E_ADMIN_LOGIN
  E2E_ADMIN_PASSWORD
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any
from urllib import error, request


BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:8000").rstrip("/")
MEMBER_LOGIN = os.getenv("E2E_MEMBER_LOGIN", "testmember")
MEMBER_PASSWORD = os.getenv("E2E_MEMBER_PASSWORD", "ChangeMe_Member@123")
ADMIN_LOGIN = os.getenv("E2E_ADMIN_LOGIN", "admin")
ADMIN_PASSWORD = os.getenv("E2E_ADMIN_PASSWORD", "ChangeMe_Admin@123")


def _http_json(method: str, path: str, token: str | None = None, body: dict[str, Any] | None = None) -> tuple[int, Any]:
    url = f"{BASE_URL}{path}"
    data = None
    headers = {"Content-Type": "application/json"}

    if token:
        headers["Authorization"] = f"Bearer {token}"

    if body is not None:
        data = json.dumps(body).encode("utf-8")

    req = request.Request(url=url, method=method, headers=headers, data=data)

    try:
        with request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
            parsed = json.loads(raw) if raw else None
            return resp.status, parsed
    except error.HTTPError as exc:
        raw = exc.read().decode("utf-8") if exc.fp else ""
        parsed = json.loads(raw) if raw else {"detail": raw}
        return exc.code, parsed


def _expect(condition: bool, message: str):
    if not condition:
        raise AssertionError(message)


def _login(username: str, password: str) -> str:
    status, payload = _http_json(
        "POST",
        "/auth/login",
        body={"username": username, "password": password},
    )
    _expect(status == 200, f"Login failed for '{username}'. status={status} payload={payload}")
    token = payload.get("access_token") if isinstance(payload, dict) else None
    _expect(bool(token), f"No access_token returned for '{username}'. payload={payload}")
    return token


def run() -> int:
    print("=" * 70)
    print("Profile Update Request Smoke Test")
    print(f"BASE_URL={BASE_URL}")
    print("=" * 70)

    # Member submits a profile update request with a harmless optional field change.
    member_token = _login(MEMBER_LOGIN, MEMBER_PASSWORD)
    print("[OK] Member login")

    status, member_profile = _http_json("GET", "/members/me", token=member_token)
    _expect(status == 200, f"GET /members/me failed. status={status} payload={member_profile}")
    current_address = member_profile.get("address") if isinstance(member_profile, dict) else None
    new_address = f"{(current_address or 'Addr').strip()} [smoke]"

    status, created_request = _http_json(
        "POST",
        "/requests/profile-update",
        token=member_token,
        body={"address": new_address},
    )
    _expect(status == 201, f"POST /requests/profile-update failed. status={status} payload={created_request}")

    _expect(created_request.get("is_profile_update") is True, "is_profile_update must be true")
    _expect(created_request.get("profile_update_member_id") is not None, "profile_update_member_id missing")
    changed = created_request.get("profile_update_changed_fields") or {}
    _expect(isinstance(changed, dict), "profile_update_changed_fields must be object")
    _expect("address" in changed, "changed fields must include address")
    request_id = created_request.get("id")
    _expect(isinstance(request_id, int), f"request id missing/invalid: {created_request}")
    print(f"[OK] Profile update request created. request_id={request_id}")

    # Admin approves the request.
    admin_token = _login(ADMIN_LOGIN, ADMIN_PASSWORD)
    print("[OK] Admin login")

    status, approved = _http_json(
        "PUT",
        f"/requests/{request_id}",
        token=admin_token,
        body={"status": "approved", "admin_response": "Approved by smoke test"},
    )
    _expect(status == 200, f"PUT /requests/{request_id} approve failed. status={status} payload={approved}")
    _expect(approved.get("status") == "approved", f"Request status not approved: {approved}")
    print("[OK] Request approved")

    # Member should receive notification.
    status, notifications = _http_json("GET", "/notifications/?skip=0&limit=50", token=member_token)
    _expect(status == 200, f"GET /notifications failed. status={status} payload={notifications}")
    _expect(isinstance(notifications, list), f"Notifications payload is not list: {notifications}")
    found_notification = any(
        isinstance(n, dict)
        and f"#{request_id}" in str(n.get("message", ""))
        and "approved" in str(n.get("message", "")).lower()
        for n in notifications
    )
    _expect(found_notification, "Expected approval notification for request owner was not found")
    print("[OK] Member notification verified")

    # Audit log should contain the profile-update approval action.
    status, logs = _http_json(
        "GET",
        "/audit-logs/?entity_type=Request&action=profile_update_request_approved&limit=100",
        token=admin_token,
    )
    _expect(status == 200, f"GET /audit-logs failed. status={status} payload={logs}")
    _expect(isinstance(logs, list), f"Audit logs payload is not list: {logs}")
    found_log = any(isinstance(log, dict) and log.get("entity_id") == request_id for log in logs)
    _expect(found_log, "Expected audit log for approved profile-update request was not found")
    print("[OK] Audit log verified")

    print("=" * 70)
    print("All smoke checks passed")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(run())
    except AssertionError as exc:
        print(f"[FAIL] {exc}")
        raise SystemExit(1)
    except Exception as exc:
        print(f"[ERROR] {exc}")
        raise SystemExit(2)
