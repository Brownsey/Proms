from pathlib import Path

from fastapi.testclient import TestClient

from proms.app import create_app


def make_ui_build(root: Path) -> Path:
    control = root / "server" / "app" / "control.html"
    control.parent.mkdir(parents=True)
    control.write_text("<!doctype html><title>Local Proms control</title>", encoding="utf-8")
    static = root / "static" / "chunks" / "control.js"
    static.parent.mkdir(parents=True)
    static.write_text("window.PROMS_CONTROL = true;", encoding="utf-8")
    return root


def test_root_redirects_to_local_control_panel(tmp_path: Path) -> None:
    with TestClient(create_app(ui_build_path=make_ui_build(tmp_path / ".next"))) as client:
        response = client.get("/", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"] == "/control/"


def test_local_control_panel_and_next_static_assets_are_served(tmp_path: Path) -> None:
    with TestClient(create_app(ui_build_path=make_ui_build(tmp_path / ".next"))) as client:
        control = client.get("/control/")
        asset = client.get("/_next/static/chunks/control.js")

    assert control.status_code == 200
    assert "Local Proms control" in control.text
    assert control.headers["content-type"].startswith("text/html")
    assert asset.status_code == 200
    assert asset.text == "window.PROMS_CONTROL = true;"


def test_missing_ui_build_returns_safe_guidance_while_health_stays_usable(
    tmp_path: Path,
) -> None:
    with TestClient(create_app(ui_build_path=tmp_path / "missing")) as client:
        control = client.get("/control/")
        health = client.get("/health")

    assert control.status_code == 503
    assert control.json() == {
        "detail": (
            "Local control panel is not built. Run scripts/setup.ps1, then restart uv run proms."
        )
    }
    assert health.status_code == 200
    assert health.json() == {"status": "ok"}
