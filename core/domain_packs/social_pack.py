"""
Social Platform Domain Pack for AetherOS.

Carries canonical entity graph, constraints, integrations, and architecture
notes for generating correct social network backends and frontends.
"""
from __future__ import annotations

from aether_os.core.domain_packs import (
    DomainPack,
    EntitySpec,
    IntegrationSpec,
)

# ── Entities ──────────────────────────────────────────────────────────────────

_ENTITIES = [
    EntitySpec(
        name="UserProfile",
        description=(
            "Public-facing profile for a registered user. Stores social metadata "
            "separate from auth credentials. username must be globally unique."
        ),
        typical_fields=[
            "id", "user_id", "username", "display_name", "bio",
            "avatar_url", "cover_image_url", "website", "location",
            "follower_count", "following_count", "post_count",
            "is_verified", "created_at",
        ],
        unique_fields=["username"],
        fk_relationships=[],
        compliance_fields=["bio", "location", "website"],  # GDPR: PII in user-generated content
        indexes=["username", "user_id"],
    ),
    EntitySpec(
        name="Post",
        description=(
            "A piece of content authored by a UserProfile. Supports text, image, "
            "and video. Visibility controls who can view the post. Soft-deleted "
            "via is_deleted flag for content moderation — never hard-delete."
        ),
        typical_fields=[
            "id", "author_id", "content", "image_url", "video_url",
            "visibility", "like_count", "comment_count", "share_count",
            "is_pinned", "is_deleted", "created_at", "updated_at",
        ],
        unique_fields=[],
        fk_relationships=["author_id -> UserProfile.id"],
        compliance_fields=["content", "image_url", "video_url"],  # GDPR: user content
        indexes=["author_id", "created_at"],
    ),
    EntitySpec(
        name="Comment",
        description=(
            "A comment on a Post. Supports threaded replies via parent_comment_id "
            "self-FK. Nested at most one level deep to avoid infinite recursion in "
            "queries — enforce in application layer."
        ),
        typical_fields=[
            "id", "post_id", "author_id", "content",
            "parent_comment_id", "like_count", "created_at",
        ],
        unique_fields=[],
        fk_relationships=[
            "post_id -> Post.id",
            "author_id -> UserProfile.id",
            "parent_comment_id -> Comment.id",
        ],
        compliance_fields=["content"],  # GDPR: user-generated text
        indexes=["post_id", "author_id"],
    ),
    EntitySpec(
        name="Like",
        description=(
            "A like on a Post or Comment. post_id and comment_id are mutually "
            "exclusive — exactly one must be non-null. Unique constraints prevent "
            "duplicate likes. Counts updated atomically via SQL UPDATE ... + 1."
        ),
        typical_fields=[
            "id", "user_id", "post_id", "comment_id", "created_at",
        ],
        unique_fields=[],  # composite uniques: (user_id, post_id), (user_id, comment_id)
        fk_relationships=[
            "user_id -> UserProfile.id",
            "post_id -> Post.id",
            "comment_id -> Comment.id",
        ],
        compliance_fields=[],
        indexes=["user_id", "post_id", "comment_id"],
    ),
    EntitySpec(
        name="Follow",
        description=(
            "A directed follow relationship between two UserProfiles. "
            "follower_id != following_id is enforced at DB level via CheckConstraint. "
            "status=pending for private profiles awaiting approval, active once accepted."
        ),
        typical_fields=[
            "id", "follower_id", "following_id", "status", "created_at",
        ],
        unique_fields=[],  # composite unique: (follower_id, following_id)
        fk_relationships=[
            "follower_id -> UserProfile.id",
            "following_id -> UserProfile.id",
        ],
        compliance_fields=[],
        indexes=["follower_id", "following_id"],
    ),
    EntitySpec(
        name="Notification",
        description=(
            "An in-app notification delivered to a recipient. type indicates the "
            "action that triggered it (like/comment/follow/mention). entity_type and "
            "entity_id reference the content that triggered the notification. "
            "is_read defaults False; batch-marked read on fetch."
        ),
        typical_fields=[
            "id", "recipient_id", "sender_id", "type", "entity_type",
            "entity_id", "message", "is_read", "created_at",
        ],
        unique_fields=[],
        fk_relationships=[
            "recipient_id -> UserProfile.id",
            "sender_id -> UserProfile.id",
        ],
        compliance_fields=["message"],  # GDPR: may contain PII from sender
        indexes=["recipient_id", "is_read"],
    ),
    EntitySpec(
        name="Hashtag",
        description=(
            "A discoverable topic tag. slug is the normalized lowercase form "
            "used for lookups. post_count is denormalized for trending queries "
            "and updated atomically via SQL UPDATE."
        ),
        typical_fields=[
            "id", "name", "slug", "post_count", "created_at",
        ],
        unique_fields=["slug"],
        fk_relationships=[],
        compliance_fields=[],
        indexes=["slug", "post_count"],
    ),
    EntitySpec(
        name="PostHashtag",
        description=(
            "Join table linking Posts to Hashtags. Unique constraint on "
            "(post_id, hashtag_id) prevents duplicate tagging."
        ),
        typical_fields=[
            "id", "post_id", "hashtag_id",
        ],
        unique_fields=[],  # composite unique: (post_id, hashtag_id)
        fk_relationships=[
            "post_id -> Post.id",
            "hashtag_id -> Hashtag.id",
        ],
        compliance_fields=[],
        indexes=["post_id", "hashtag_id"],
    ),
]

# ── Integrations ──────────────────────────────────────────────────────────────

_INTEGRATIONS = [
    IntegrationSpec(
        name="sendgrid",
        purpose="Email notifications — new follower alerts, mention digests, account security",
        env_vars=["SENDGRID_API_KEY", "SENDGRID_FROM_EMAIL"],
        typical_methods=[
            "send_follow_notification",
            "send_mention_digest",
            "send_account_verification",
        ],
    ),
    IntegrationSpec(
        name="twilio",
        purpose="SMS 2FA for account security; critical activity alerts",
        env_vars=["TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER"],
        typical_methods=["client.messages.create"],
    ),
    IntegrationSpec(
        name="cloudinary",
        purpose="Image and video upload, transformation, and CDN delivery",
        env_vars=["CLOUDINARY_CLOUD_NAME", "CLOUDINARY_API_KEY", "CLOUDINARY_API_SECRET"],
        typical_methods=[
            "cloudinary.uploader.upload",
            "cloudinary.CloudinaryVideo",
            "cloudinary.utils.cloudinary_url",
        ],
    ),
    IntegrationSpec(
        name="pusher",
        purpose="Real-time WebSocket notifications for likes, comments, and follows",
        env_vars=["PUSHER_APP_ID", "PUSHER_KEY", "PUSHER_SECRET", "PUSHER_CLUSTER"],
        typical_methods=[
            "pusher_client.trigger",
            "pusher_client.trigger_batch",
        ],
    ),
]

# ── Constraints ───────────────────────────────────────────────────────────────

_CONSTRAINTS = [
    "A user CANNOT follow themselves — enforce via DB CheckConstraint: "
    "CheckConstraint('follower_id != following_id', name='ck_follow_no_self_follow').",
    "Post visibility MUST be checked before serving to non-followers: "
    "'public' = anyone; 'friends' = mutual follows only; 'private' = author only.",
    "Like counts MUST be updated atomically: "
    "UPDATE post SET like_count = like_count + 1 — never read-then-write.",
    "Posts MUST be soft-deleted: set is_deleted=True rather than DELETE. "
    "Hard delete only on GDPR erasure request after 30-day grace period.",
    "GDPR: user can request full data export (all Posts, Comments, Likes, Follows). "
    "Mark PII fields in compliance_fields. Export endpoint must complete in < 60 seconds.",
    "Rate limit: max 100 posts per day per user — enforce in application layer "
    "using a Redis counter keyed by user_id + date.",
    "Rate limit: max 1000 likes per day per user — same Redis counter pattern.",
    "Like uniqueness: enforce UNIQUE constraints on (user_id, post_id) and "
    "(user_id, comment_id) in the DB to prevent duplicate likes on re-click.",
    "Follow uniqueness: enforce UNIQUE constraint on (follower_id, following_id).",
    "PostHashtag uniqueness: enforce UNIQUE constraint on (post_id, hashtag_id).",
    "Comment nesting: allow at most one level of replies (parent_comment_id may "
    "point to a top-level comment only) — validate in application layer.",
    "Notification delivery: fanout-on-write for users with < 1000 followers; "
    "fanout-on-read for users with >= 1000 followers (celebrity problem).",
]

# ── Seed patterns ─────────────────────────────────────────────────────────────

_SEED_PATTERNS = {
    "username": "user_{i:05d}",
    "display_name": "User {i}",
    "email": "user{i}@example.com",
    "slug": "{entity_lower}-{i}",
    "avatar_url": "https://cdn.example.com/avatars/{i}.jpg",
    "cover_image_url": "https://cdn.example.com/covers/{i}.jpg",
    "url": "https://cdn.example.com/posts/{i}.jpg",
    "website": "https://example.com/user{i}",
}

# ── Architecture notes ────────────────────────────────────────────────────────

_ARCHITECTURE_NOTES = [
    "Activity feed: store in Redis as a sorted set (score = Unix timestamp) "
    "keyed by user_id. Fanout-on-write for < 1000 followers; fanout-on-read "
    "for celebrities to avoid write amplification.",
    "Feed queries: use read replicas for feed SELECT queries — never hit the "
    "primary DB for high-volume feed reads.",
    "Media: all image/video fields store CDN URL references only (Cloudinary). "
    "Never store binary blobs in the database.",
    "Hashtag trending: maintain a sorted set in Redis (score = post_count) "
    "for O(1) top-N trending hashtag queries.",
    "Counters: like_count, comment_count, follower_count are denormalized for "
    "read performance. Update atomically via SQL; reconcile with background job hourly.",
    "Real-time: use Pusher channels (private-user-{id}) for per-user notification "
    "delivery. Fall back to polling if WebSocket not available.",
    "Content moderation: soft-delete via is_deleted flag preserves audit trail. "
    "A background moderation queue processes flagged content asynchronously.",
    "Search: add PostgreSQL GIN full-text index on Post.content for keyword search. "
    "Index Hashtag.slug for tag-based search.",
]

# ── Pack instance ─────────────────────────────────────────────────────────────

SOCIAL_PACK = DomainPack(
    domain="social",
    display_name="Social Platform",
    description=(
        "Social networking platform supporting user profiles, posts, comments, "
        "likes, follows, hashtags, activity feeds, and real-time notifications."
    ),
    typical_entities=_ENTITIES,
    constraints=_CONSTRAINTS,
    compliance_standards=["GDPR"],
    typical_integrations=_INTEGRATIONS,
    seed_patterns=_SEED_PATTERNS,
    architecture_notes=_ARCHITECTURE_NOTES,
)

__all__ = ["SOCIAL_PACK"]
