from __future__ import annotations

import re
from typing import get_args

from app.conversation.pending_actions import PENDING_ACTIONS, PendingAction


def test_pending_action_literal_matches_states_catalog() -> None:
    with open("docs/conversation/states.md", encoding="utf-8") as document:
        content = document.read()

    section = re.search(
        r"# 20\. Acciones pendientes oficiales\s+```text\n(?P<body>.*?)\n```",
        content,
        re.DOTALL,
    )
    assert section is not None
    documented = tuple(
        line.strip() for line in section.group("body").splitlines() if line.strip()
    )

    assert get_args(PendingAction) == documented
    assert PENDING_ACTIONS == documented
