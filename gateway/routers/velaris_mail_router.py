"""Mail proxy: /mail/* -> Velaris /mail/*. Table of the routes the dashboard uses; rules in gateway/velaris_proxy.py.
Mail attachments travel inside draft JSON (Velaris has no raw upload route), so they share the 64 KiB cap."""
from __future__ import annotations

from aether_os.gateway.velaris_proxy import Route as R, build_router

MB = "/mailboxes/{mb}"
ROUTES = (
    R("GET", "/mailboxes", "mail.mailboxes"),
    R("GET", MB + "/folders", "mail.folders"),
    R("POST", MB + "/folders", "mail.folder.create"),
    R("GET", MB + "/messages", "mail.messages"),
    R("GET", MB + "/messages/{mid}", "mail.message"),
    R("PATCH", MB + "/messages/{mid}", "mail.message.update", ledger=False),   # seen/flag toggles
    R("DELETE", MB + "/messages/{mid}", "mail.message.delete"),
    R("POST", MB + "/messages/{mid}/restore", "mail.message.restore"),
    R("GET", MB + "/messages/{mid}/attachments/{sha}", "mail.attachment", kind="download"),
    R("GET", MB + "/threads/{tid}", "mail.thread"),
    R("POST", MB + "/drafts", "mail.draft.create", ledger=False),
    R("PUT", MB + "/drafts/{did}", "mail.draft.update", ledger=False),
    R("DELETE", MB + "/drafts/{did}", "mail.draft.delete", ledger=False),
    R("POST", MB + "/drafts/{did}/submit", "mail.submit"),
    R("GET", MB + "/submissions", "mail.submissions"),
    R("GET", "/submissions/{sid}", "mail.submission"),
    R("POST", "/submissions/{sid}/cancel", "mail.submission.cancel"),
    R("POST", "/submissions/{sid}/decide", "mail.submission.decide", log=("approve", "payload_hash")),
    R("GET", "/approvals", "mail.approvals"),
    R("GET", MB + "/rules", "mail.rules"),
    R("POST", MB + "/rules", "mail.rule.create"),
    R("POST", MB + "/rules/dry-run", "mail.rule.dry_run", ledger=False),
    R("PUT", MB + "/rules/{rid}", "mail.rule.update"),
    R("DELETE", MB + "/rules/{rid}", "mail.rule.delete"),
    R("GET", MB + "/settings", "mail.mailbox.settings"),
    R("PUT", MB + "/settings", "mail.mailbox.settings.set"),
    R("POST", MB + "/assistant/summarise", "mail.assistant.summarise"),
    R("POST", MB + "/assistant/action-items", "mail.assistant.action_items"),
    R("POST", MB + "/assistant/triage", "mail.assistant.triage"),
    R("POST", MB + "/assistant/draft-reply", "mail.assistant.draft_reply"),
    R("GET", "/domains", "mail.domains"),
    R("POST", "/domains", "mail.domain.claim", log=("domain",)),
    R("POST", "/domains/verify", "mail.domain.verify", log=("domain",)),
    R("GET", "/settings", "mail.settings"),
    R("GET", "/settings/dkim", "mail.dkim"),
    R("GET", MB + "/export", "mail.export", ledger=True),
)
router = build_router("/mail", "/mail", ROUTES, "velaris-mail")
