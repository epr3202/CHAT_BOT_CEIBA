from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"


def test_frontend_files_are_self_contained() -> None:
    expected = {
        "index.html",
        "styles.css",
        "app.js",
        "server.mjs",
        "README.md",
    }

    assert expected <= {path.name for path in FRONTEND.iterdir()}


def test_frontend_uses_only_current_backend_surfaces() -> None:
    app_js = FRONTEND.joinpath("app.js").read_text(encoding="utf-8")
    server = FRONTEND.joinpath("server.mjs").read_text(encoding="utf-8")
    allowed_paths = {
        "/api/health",
        "/api/admin/handoffs",
        "/api/admin/handoffs/",
        "/api/admin/conversations/",
        "/api/webhook/simulate",
        "/health",
        "/admin/handoffs",
        "/admin/conversations/",
        "/webhook",
    }

    used_paths = {
        token
        for token in app_js.replace('"', "'").split("'")
        if token.startswith(("/api/", "/admin/", "/health", "/webhook"))
    }
    used_paths.update(
        token
        for token in server.replace('"', "'").split("'")
        if token.startswith(("/api/", "/admin/", "/health", "/webhook"))
    )

    unexpected = {
        path
        for path in used_paths
        if not any(path == allowed or path.startswith(allowed) for allowed in allowed_paths)
    }
    assert unexpected == set()


def test_frontend_server_keeps_webhook_secret_out_of_logs() -> None:
    server = FRONTEND.joinpath("server.mjs").read_text(encoding="utf-8")

    assert "metaSecret" in server
    assert "console.log(metaSecret" not in server
    assert "console.error(metaSecret" not in server
    assert "createHmac" in server


def test_admin_cases_require_token_before_fetching() -> None:
    app_js = FRONTEND.joinpath("app.js").read_text(encoding="utf-8")
    function_start = app_js.index("async function loadAllAdminCases()")
    function_end = app_js.index("function caseFromHandoff", function_start)
    function_body = app_js[function_start:function_end]

    assert "state.adminToken" in function_body
    assert function_body.index("state.adminToken") < function_body.index("/api/admin/handoffs")
    assert ".catch(() => [])" not in function_body
