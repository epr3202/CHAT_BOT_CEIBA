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
        "/api/admin/conversations",
        "/api/admin/conversations/",
        "/api/admin/me",
        "/api/webhook/simulate",
        "/health",
        "/admin/handoffs",
        "/admin/conversations",
        "/admin/conversations/",
        "/admin/me",
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
    assert "process.env.META_APP_SECRET" in server
    assert "console.log(metaSecret" not in server
    assert "console.error(metaSecret" not in server
    assert "createHmac" in server


def test_conversations_require_operation_token_before_fetching() -> None:
    app_js = FRONTEND.joinpath("app.js").read_text(encoding="utf-8")
    function_start = app_js.index("async function loadAllAdminCases()")
    function_end = app_js.index("function caseFromHandoff", function_start)
    function_body = app_js[function_start:function_end]

    assert "hasOperationToken()" in function_body
    assert function_body.index("hasOperationToken()") < function_body.index(
        "/api/admin/conversations"
    )
    assert ".catch(() => [])" not in function_body


def test_admin_token_uses_session_storage_with_legacy_migration() -> None:
    app_js = FRONTEND.joinpath("app.js").read_text(encoding="utf-8")

    assert 'sessionStorage.getItem(adminTokenStorageKey)' in app_js
    assert 'sessionStorage.setItem(adminTokenStorageKey, legacyToken)' in app_js
    assert 'localStorage.removeItem(adminTokenStorageKey)' in app_js
    assert 'localStorage.setItem("ceiba.adminToken"' not in app_js


def test_agent_document_id_uses_local_storage_and_resolves_identity() -> None:
    app_js = FRONTEND.joinpath("app.js").read_text(encoding="utf-8")
    index_html = FRONTEND.joinpath("index.html").read_text(encoding="utf-8")

    assert 'const agentTokenStorageKey = "ceiba.agentToken"' in app_js
    assert 'const agentDocumentIdStorageKey = "ceiba.agentDocumentId"' in app_js
    assert "localStorage.getItem(agentDocumentIdStorageKey)" in app_js
    assert "localStorage.setItem(agentDocumentIdStorageKey, state.agentDocumentId)" in app_js
    assert "sessionStorage.removeItem(agentTokenStorageKey)" in app_js
    assert "/api/admin/me" in app_js
    assert 'id="agentState"' in index_html
    assert 'id="agentDocumentId"' in index_html


def test_agent_message_refreshes_handoff_view() -> None:
    app_js = FRONTEND.joinpath("app.js").read_text(encoding="utf-8")
    function_start = app_js.index("async function sendAgentMessage")
    function_end = app_js.index("async function returnHandoff", function_start)
    function_body = app_js[function_start:function_end]

    assert "await refreshAll();" in function_body


def test_handoff_chat_uses_ajax_polling() -> None:
    app_js = FRONTEND.joinpath("app.js").read_text(encoding="utf-8")
    index_html = FRONTEND.joinpath("index.html").read_text(encoding="utf-8")

    assert 'class="chatThread"' in index_html
    assert "/api/admin/conversations/${conversationId}/messages" in app_js
    assert "setInterval(refreshVisibleHandoffMessages, state.chatPollIntervalMs)" in app_js
    assert "function renderChatThread" in app_js


def test_admin_cases_list_conversations_and_can_take_any_chat() -> None:
    app_js = FRONTEND.joinpath("app.js").read_text(encoding="utf-8")
    server = FRONTEND.joinpath("server.mjs").read_text(encoding="utf-8")

    assert "requestJson(`/api/admin/conversations?${params.toString()}`" in app_js
    assert "function takeConversation" in app_js
    assert "/api/admin/conversations/${conversationId}/take" in app_js
    assert 'path === "/api/admin/conversations"' in server


def test_frontend_has_conversation_filters_and_direct_take_uses_agent_token() -> None:
    app_js = FRONTEND.joinpath("app.js").read_text(encoding="utf-8")
    index_html = FRONTEND.joinpath("index.html").read_text(encoding="utf-8")

    assert 'id="conversationStateFilter"' in index_html
    assert 'id="assignedToMeFilter"' in index_html
    assert 'state.assignedToMe && state.agentDocumentId' in app_js
    assert 'params.set("assigned_to_me", "true")' in app_js
    function_start = app_js.index("async function takeConversation")
    function_end = app_js.index("async function sendAgentMessage", function_start)
    function_body = app_js[function_start:function_end]
    assert "headers: operationHeaders()" in function_body
    assert 'options.body = JSON.stringify({ agent: "ADMIN" })' in function_body
    assert "prompt(" not in app_js
    assert "alert(" not in app_js


def test_frontend_shows_assignment_history() -> None:
    app_js = FRONTEND.joinpath("app.js").read_text(encoding="utf-8")
    styles = FRONTEND.joinpath("styles.css").read_text(encoding="utf-8")

    assert "assignment_history" in app_js
    assert "function assignmentText" in app_js
    assert "white-space: pre-line" in styles
