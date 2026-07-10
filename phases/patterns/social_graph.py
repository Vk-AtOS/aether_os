"""Social graph backend pattern — follow graph, feed, notifications, hashtags.

Model names are hard-coded to canonical defaults (User, UserProfile, Follow,
Post, Hashtag, PostHashtag, Like, Notification).  To resolve names from the
actual IR entities, use generate_social_pattern() from pattern_name_resolver
instead of this constant.

Template code lives in social_graph_templates.py (extracted to stay under the
600-line file limit).
"""
from __future__ import annotations

try:
    from aether_os.phases.patterns.social_graph_templates import _build_social_code
except ImportError:
    from phases.patterns.social_graph_templates import _build_social_code  # type: ignore[no-redef]

SOCIAL_GRAPH_REQUIREMENTS = ["redis>=5.0", "cloudinary>=1.36"]

# Default canonical model names used when the caller does not supply an entity_map.
_SOCIAL_DEFAULT_ENTITY_MAP: dict = {
    "user_profile": "UserProfile",
    "follow": "Follow",
    "post": "Post",
    "hashtag": "Hashtag",
    "post_hashtag": "PostHashtag",
    "like": "Like",
    "notification": "Notification",
}


def get_social_code(entity_map: dict | None = None) -> str:
    """Return social graph router source with IR-resolved model names.
    entity_map keys: user_profile, follow, post, hashtag, post_hashtag, like, notification.
    Unknown keys fall back to canonical defaults. Pass None to use canonical names.
    """
    em = dict(_SOCIAL_DEFAULT_ENTITY_MAP)
    if entity_map:
        em.update(entity_map)
    return _build_social_code(
        user_profile=em.get("user_profile", "UserProfile"),
        follow=em.get("follow", "Follow"),
        post=em.get("post", "Post"),
        hashtag=em.get("hashtag", "Hashtag"),
        post_hashtag=em.get("post_hashtag", "PostHashtag"),
        like=em.get("like", "Like"),
        notification=em.get("notification", "Notification"),
    )


# Backward-compatible constant — uses canonical (default) model names.
SOCIAL_GRAPH_CODE = get_social_code()
__all__ = ["SOCIAL_GRAPH_CODE", "SOCIAL_GRAPH_REQUIREMENTS", "get_social_code"]
