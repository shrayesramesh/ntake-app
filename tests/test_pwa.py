"""PWA installability (DISP): web app manifest + a minimal service worker.

The phones and the wall tablet run the app by "add to home screen" (§3), which
requires a linked manifest and a registered service worker served from the app's
own origin. v1 keeps the SW deliberately **pass-through (no caching)**: the app
is a live server (a cached shell would risk showing stale board/calendar), so the
SW exists for installability, not offline. These tests pin the routes + wiring.
"""

from __future__ import annotations

import json


def test_manifest_served_with_manifest_content(client):
    r = client.get("/manifest.webmanifest")
    assert r.status_code == 200
    assert "manifest" in r.headers["content-type"]
    data = json.loads(r.text)
    # The fields a browser needs to offer "install / add to home screen".
    assert data["name"]
    assert data["start_url"] == "/"
    assert data["display"] in {"standalone", "fullscreen", "minimal-ui"}
    assert isinstance(data.get("icons"), list) and data["icons"]


def test_service_worker_served_as_javascript(client):
    r = client.get("/sw.js")
    assert r.status_code == 200
    assert "javascript" in r.headers["content-type"]
    # Minimal but real: it registers lifecycle handlers. v1 is pass-through — it
    # must NOT cache responses (a live app shouldn't serve a stale shell).
    assert "install" in r.text and "activate" in r.text
    assert "caches.open" not in r.text  # no precache/runtime cache in v1


def test_shell_links_manifest_and_registers_service_worker(client):
    body = client.get("/").text
    assert 'rel="manifest"' in body
    assert "/manifest.webmanifest" in body
    assert "serviceWorker" in body
    assert "/sw.js" in body
    # theme-color helps the installed PWA chrome; a small nicety browsers expect.
    assert 'name="theme-color"' in body
