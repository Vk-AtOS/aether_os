"""Chat proxy: /chat/* -> Velaris /chat/*. A table of the routes the dashboard uses (see gateway/velaris_proxy.py
for the rules: signed identity from the DB row, 503 handling, size caps, ledger of state changes)."""
from __future__ import annotations

from aether_os.gateway.velaris_proxy import CALL_TIMEOUT_S as SLOW, Route as R, build_router

_NL = False     # not ledgered: chatty or trivial (register, read markers, drafts, reactions, pins)
ROUTES = (
    R("POST", "/register", "chat.register", ledger=_NL),
    R("GET", "/events", "chat.events", kind="poll"),
    R("GET", "/events/stream", "chat.events.stream", kind="sse"),
    R("DELETE", "/queues/{queue_id}", "chat.queue.drop", ledger=_NL),
    R("GET", "/channels", "chat.channels"),
    R("GET", "/channels/public", "chat.channels.public"),
    R("POST", "/channels", "chat.channel.create"),
    R("GET", "/channels/{channel_id}", "chat.channel.get"),
    R("PATCH", "/channels/{channel_id}", "chat.channel.update"),
    R("POST", "/channels/{channel_id}/join", "chat.channel.join"),
    R("POST", "/channels/{channel_id}/leave", "chat.channel.leave"),
    R("POST", "/channels/{channel_id}/members", "chat.member.add", log=("user_id",)),
    R("DELETE", "/channels/{channel_id}/members/{user_id}", "chat.member.remove"),
    R("PUT", "/channels/{channel_id}/members/{user_id}/role", "chat.member.role", log=("role",)),
    R("GET", "/channels/{channel_id}/messages", "chat.messages"),
    R("POST", "/channels/{channel_id}/messages", "chat.message.post"),
    R("GET", "/channels/{channel_id}/topics", "chat.topics"),
    R("GET", "/channels/{channel_id}/pins", "chat.pins"),
    R("POST", "/channels/{channel_id}/read", "chat.read", ledger=_NL),
    R("PUT", "/channels/{channel_id}/draft", "chat.draft.set", ledger=_NL),
    R("GET", "/drafts", "chat.drafts"),
    R("PATCH", "/messages/{message_id}", "chat.message.edit"),
    R("DELETE", "/messages/{message_id}", "chat.message.delete"),
    R("GET", "/messages/{message_id}/history", "chat.message.history"),
    R("GET", "/messages/{message_id}/unfurl", "chat.message.unfurl"),
    R("PUT", "/messages/{message_id}/reactions/{emoji}", "chat.react", ledger=_NL),
    R("DELETE", "/messages/{message_id}/reactions/{emoji}", "chat.unreact", ledger=_NL),
    R("PUT", "/messages/{message_id}/pin", "chat.pin", ledger=_NL),
    R("DELETE", "/messages/{message_id}/pin", "chat.unpin", ledger=_NL),
    R("GET", "/search", "chat.search"),
    R("POST", "/files", "chat.file.upload", kind="upload"),
    R("GET", "/files/{digest}", "chat.file.download", kind="download"),
    # assistant
    R("GET", "/assistant/drafts", "chat.assistant.drafts"),
    R("POST", "/assistant/drafts/{draft_id}/confirm", "chat.assistant.draft.confirm"),
    R("POST", "/assistant/drafts/{draft_id}/discard", "chat.assistant.draft.discard"),
    R("GET", "/assistant/proposals", "chat.assistant.proposals"),
    R("POST", "/assistant/proposals/{run_id}/confirm", "chat.assistant.proposal.confirm", log=("call_hash",)),
    R("POST", "/assistant/proposals/{run_id}/decide", "chat.assistant.proposal.decide", log=("call_hash", "approve")),
    # admin / compliance: owner/admin checked here (D7), Velaris applies its own roles on top
    R("GET", "/admin/settings", "chat.admin.settings", admin=True, needs="chat_admin"),
    R("PUT", "/admin/settings", "chat.admin.settings.set", admin=True, needs="chat_admin"),
    R("PUT", "/admin/channels/{channel_id}/hold", "chat.admin.hold", log=("hold",), admin=True, needs="chat_admin"),
    R("GET", "/admin/channels/{channel_id}/export", "chat.admin.export", kind="export", admin=True, needs="chat_admin"),
    R("POST", "/admin/sweep", "chat.admin.sweep", admin=True, needs="chat_admin"),
    R("POST", "/admin/messages/{message_id}/erase", "chat.admin.erase", admin=True, needs="chat_admin"),
    # KAN-129 DPDP: one person's chat data. Export is a download and ledgered; erase needs the typed word.
    R("GET", "/admin/users/{user_id}/export", "chat.admin.user.export", kind="export", admin=True, needs="chat_admin", timeout=SLOW),
    R("POST", "/admin/users/{user_id}/erase", "chat.admin.user.erase", admin=True, needs="chat_admin", confirm="ERASE", timeout=SLOW),
    R("GET", "/me/export", "chat.me.export", kind="export"),
)
router = build_router("/chat", "/chat", ROUTES, "velaris-chat")
