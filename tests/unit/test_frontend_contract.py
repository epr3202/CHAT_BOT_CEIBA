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
        "/api/admin/login",
        "/api/admin/logout",
        "/api/admin/agents",
        "/api/admin/agents/",
        "/api/admin/catalogs",
        "/api/admin/catalogs/",
        "/api/webhook/simulate",
        "/health",
        "/admin/handoffs",
        "/admin/conversations",
        "/admin/conversations/",
        "/admin/me",
        "/admin/login",
        "/admin/logout",
        "/admin/agents",
        "/admin/agents/",
        "/admin/catalogs",
        "/admin/catalogs/",
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


def test_session_token_uses_session_storage_and_removes_legacy_auth() -> None:
    app_js = FRONTEND.joinpath("app.js").read_text(encoding="utf-8")

    assert 'const sessionTokenStorageKey = "ceiba.sessionToken"' in app_js
    assert "sessionStorage.getItem(sessionTokenStorageKey)" in app_js
    assert "sessionStorage.setItem(sessionTokenStorageKey, state.sessionToken)" in app_js
    assert "localStorage.removeItem(legacyAgentDocumentIdStorageKey)" in app_js
    assert "localStorage.removeItem(legacyAdminTokenStorageKey)" in app_js
    assert 'localStorage.setItem("ceiba.adminToken"' not in app_js


def test_login_uses_document_id_and_pin_without_auto_registration() -> None:
    app_js = FRONTEND.joinpath("app.js").read_text(encoding="utf-8")
    index_html = FRONTEND.joinpath("index.html").read_text(encoding="utf-8")

    assert "/api/admin/login" in app_js
    assert "/api/admin/logout" in app_js
    assert "document_id: state.documentId" in app_js
    assert "pin" in app_js
    assert "/api/admin/me" in app_js
    assert 'id="agentState"' in index_html
    assert 'id="documentId"' in index_html
    assert 'id="pin"' in index_html
    assert "function ensureAgentRegistered" not in app_js


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
    assert 'path === "/api/admin/agents"' in server


def test_frontend_has_conversation_filters_and_direct_take_uses_agent_token() -> None:
    app_js = FRONTEND.joinpath("app.js").read_text(encoding="utf-8")
    index_html = FRONTEND.joinpath("index.html").read_text(encoding="utf-8")

    assert 'id="conversationStateFilter"' in index_html
    assert 'id="assignedToMeFilter"' in index_html
    assert 'if (state.assignedToMe) params.set("assigned_to_me", "true")' in app_js
    assert 'params.set("assigned_to_me", "true")' in app_js
    function_start = app_js.index("async function takeConversation")
    function_end = app_js.index("async function sendAgentMessage", function_start)
    function_body = app_js[function_start:function_end]
    assert "headers: sessionHeaders()" in function_body
    assert "await resolveAgentIdentity()" in function_body
    assert 'options.body = JSON.stringify({ agent: "ADMIN" })' not in function_body
    assert "prompt(" not in app_js
    assert "alert(" not in app_js


def test_frontend_fetches_assignment_history_on_detail() -> None:
    app_js = FRONTEND.joinpath("app.js").read_text(encoding="utf-8")
    styles = FRONTEND.joinpath("styles.css").read_text(encoding="utf-8")

    assert "/api/admin/conversations/${conversationId}/history" in app_js
    assert "function loadAssignmentHistory" in app_js
    assert "function assignmentText" in app_js
    assert "white-space: pre-line" in styles


def test_frontend_avoids_dynamic_inner_html() -> None:
    app_js = FRONTEND.joinpath("app.js").read_text(encoding="utf-8")

    assert ".innerHTML" not in app_js


def test_frontend_summary_button_opens_modal() -> None:
    app_js = FRONTEND.joinpath("app.js").read_text(encoding="utf-8")
    index_html = FRONTEND.joinpath("index.html").read_text(encoding="utf-8")
    styles = FRONTEND.joinpath("styles.css").read_text(encoding="utf-8")

    assert 'id="summaryModal"' in index_html
    assert 'id="summaryModalBody"' in index_html
    assert "function showSummary" in app_js
    assert '$("#summaryModal").hidden = false' in app_js
    assert "function closeSummaryModal" in app_js
    assert "conversation.handoff_summary" in app_js
    assert ".modalBackdrop" in styles


def test_frontend_persists_followup_bandeja_state() -> None:
    app_js = FRONTEND.joinpath("app.js").read_text(encoding="utf-8")

    assert 'const currentStatusStorageKey = "ceiba.currentStatus"' in app_js
    assert 'const assignedToMeStorageKey = "ceiba.assignedToMe"' in app_js
    assert "function persistViewState" in app_js
    assert "localStorage.getItem(currentStatusStorageKey)" in app_js
    assert "localStorage.setItem(currentStatusStorageKey, state.currentStatus)" in app_js


def test_frontend_has_catalogs_by_category_module_and_direct_upload() -> None:
    app_js = FRONTEND.joinpath("app.js").read_text(encoding="utf-8")
    index_html = FRONTEND.joinpath("index.html").read_text(encoding="utf-8")
    styles = FRONTEND.joinpath("styles.css").read_text(encoding="utf-8")
    server = FRONTEND.joinpath("server.mjs").read_text(encoding="utf-8")

    assert 'id="catalogsModule"' in index_html
    assert 'id="catalogUploadForm"' in index_html
    assert 'id="catalogEventType"' in index_html
    assert 'type="file"' in index_html
    assert 'accept="application/pdf,.pdf"' in index_html
    assert "/api/admin/catalogs/categories" in app_js
    assert "/api/admin/catalogs/upload" in app_js
    assert "FormData" in app_js
    assert "Sin cobertura" in app_js
    assert "Atención manual" in app_js
    assert "function renderCatalogCategories" in app_js
    assert 'path === "/api/admin/catalogs/categories"' in server
    assert 'path === "/api/admin/catalogs/upload"' in server
    assert ".catalog" in styles


def test_compose_catalog_volume_is_rw_only_for_app() -> None:
    compose = ROOT.joinpath("docker-compose.yml").read_text(encoding="utf-8")
    app_section = compose[compose.index("  app:") : compose.index("  worker:")]
    worker_section = compose[compose.index("  worker:") :]

    assert "/opt/ceiba/catalogs:/data/catalogs:ro" not in app_section
    assert "/opt/ceiba/catalogs:/data/catalogs" in app_section
    assert "/opt/ceiba/catalogs:/data/catalogs:ro" in worker_section


def test_frontend_proxy_preserves_binary_multipart_body() -> None:
    server = FRONTEND.joinpath("server.mjs").read_text(encoding="utf-8")

    assert "async function readRawBody(request)" in server
    assert "Buffer.concat(chunks)" in server
    assert "await readRawBody(request)" in server
