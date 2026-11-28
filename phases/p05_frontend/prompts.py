"""P05 Frontend — domain detection data, prompt strings, and domain widget configs.

This module holds all the large data-driven dictionaries and prompt constants
used by the frontend code-generation phase agent.
"""
from __future__ import annotations

from typing import Dict, List

from aether_os.phases.p05_frontend.design_system import get_design_tokens


def get_domain_color_hint(domain: str) -> str:
    """The color hint for LLM prompts: the run's semantic token classes (KAN-243), never a per-domain palette."""
    t = get_design_tokens(domain)
    accent = t["accent"]
    bg_page = t["bg_page"].replace("bg-", "")
    text_p = t["text_primary"].replace("text-", "")
    bg_card = t["bg_card"].replace("bg-", "")
    border = t["border"].replace("border-", "")
    return (
        f"{accent} palette: bg-{bg_page}, text-{text_p}, "
        f"cards bg-{bg_card} border-{border}, accents {accent}"
    )



# ── Icon mapping ───────────────────────────────────────────────────────────────
LUCIDE_ICON_MAP: Dict[str, str] = {
    "user": "Users",
    "customer": "Users",
    "client": "Users",
    "contact": "Users",
    "employee": "Users",
    "patient": "Users",
    "student": "GraduationCap",
    "member": "Users",
    "order": "ShoppingCart",
    "cart": "ShoppingCart",
    "purchase": "ShoppingCart",
    "sale": "ShoppingCart",
    "product": "Package",
    "item": "Package",
    "inventory": "Package",
    "stock": "Package",
    "asset": "Package",
    "post": "FileText",
    "article": "FileText",
    "document": "FileText",
    "file": "FileText",
    "report": "FileText",
    "invoice": "FileText",
    "receipt": "FileText",
    "event": "Calendar",
    "booking": "Calendar",
    "appointment": "Calendar",
    "schedule": "Calendar",
    "shift": "Clock",
    "message": "MessageSquare",
    "comment": "MessageSquare",
    "chat": "MessageSquare",
    "ticket": "Ticket",
    "issue": "AlertCircle",
    "alert": "Bell",
    "notification": "Bell",
    "category": "Tag",
    "tag": "Tag",
    "lead": "TrendingUp",
    "deal": "Briefcase",
    "pipeline": "Briefcase",
    "project": "Briefcase",
    "task": "CheckSquare",
    "todo": "CheckSquare",
    "payment": "CreditCard",
    "transaction": "CreditCard",
    "sensor": "Cpu",
    "device": "Cpu",
    "gateway": "Wifi",
    "metric": "BarChart3",
    "log": "Activity",
    "review": "Star",
    "rating": "Star",
    "campaign": "Megaphone",
    "course": "BookOpen",
    "lesson": "BookOpen",
    "grade": "Award",
    "property": "Home",
    "vehicle": "Truck",
    "shipment": "Truck",
    "location": "MapPin",
    "address": "MapPin",
    "setting": "Settings",
    "config": "Settings",
}

# All icons actually used — collected from the map values
ALL_USED_ICONS = sorted(set(LUCIDE_ICON_MAP.values()))

# ── Entity emoji map ───────────────────────────────────────────────────────────
ENTITY_EMOJI_MAP: Dict[str, str] = {
    "product": "🛍️", "item": "📦", "categor": "🏷️", "cart": "🛒", "order": "📋",
    "payment": "💳", "review": "⭐", "customer": "👤", "user": "👥", "coupon": "🎟️",
    "shipping": "🚚", "brand": "🏪", "discount": "💸", "wishlist": "❤️",
    "collection": "🗂️", "sku": "🔖", "service": "✨", "package": "📦",
}

# ── Domain keyword scoring for detection ──────────────────────────────────────
DOMAIN_KEYWORDS: Dict[str, List] = {
    "security":            [("camera", 3), ("cctv", 3), ("surveillance", 3), ("footage", 3),
                            ("nvr", 3), ("dvr", 3), ("ptz", 3), ("facial recognition", 3),
                            ("intrusion", 2), ("motion detection", 2), ("security camera", 3),
                            ("access control", 1), ("guard", 2), ("zone", 1), ("feed", 1)],
    "iot":                 [("sensor", 2), ("telemetry", 3), ("mqtt", 3), ("firmware", 3),
                            ("iot", 3), ("embedded", 2), ("actuator", 2), ("arduino", 3),
                            ("raspberry pi", 3), ("temperature sensor", 3), ("humidity", 2),
                            ("edge computing", 2), ("device", 1)],
    "healthcare":          [("patient", 3), ("appointment", 2), ("doctor", 2), ("clinic", 2),
                            ("medical", 2), ("prescription", 3), ("diagnosis", 3),
                            ("vitals", 3), ("nurse", 2), ("ehr", 3), ("emr", 3), ("health", 1)],
    "crm":                 [("crm", 3), ("lead", 2), ("deal", 2), ("opportunity", 2),
                            ("prospect", 2), ("sales pipeline", 3), ("funnel", 2),
                            ("contact", 1), ("sales", 1)],
    "ecommerce":           [("cart", 3), ("sku", 3), ("ecommerce", 3), ("storefront", 3),
                            ("add to cart", 3), ("shop", 2), ("store", 2), ("order", 2),
                            ("product", 1), ("payment", 1), ("purchase", 1)],
    "library":             [("library", 3), ("isbn", 3), ("librarian", 3), ("borrow", 3),
                            ("overdue", 3), ("book tracking", 3), ("catalog", 2), ("book", 2),
                            ("reading", 2), ("shelf", 2), ("member", 1)],
    "hrm":                 [("employee", 3), ("payroll", 3), ("attendance", 3), ("leave request", 3),
                            ("department", 2), ("salary", 3), ("human resources", 3),
                            ("workforce", 3), ("hrm", 3), ("hr platform", 3),
                            ("onboarding", 2), ("hire", 2), (" hr ", 2), ("hris", 3)],
    "finance":             [("invoice", 3), ("expense", 2), ("budget", 2), ("ledger", 3),
                            ("transaction", 2), ("accounting", 3), ("billing", 2),
                            ("financial", 2), ("payment", 1), ("account", 1)],
    "project_management":  [("sprint", 3), ("kanban", 3), ("backlog", 3), ("milestone", 2),
                            ("ticket", 2), ("board", 2), ("task", 1), ("project", 1)],
    "restaurant":          [("restaurant", 3), ("menu", 2), ("table", 2), ("reservation", 2),
                            ("kitchen", 2), ("waiter", 2), ("dish", 2), ("pos", 2)],
    "education":           [("student", 3), ("enrollment", 3), ("grade", 2), ("teacher", 2),
                            ("course", 2), ("lesson", 2), ("school", 2), ("class", 1)],
    "gym_fitness":         [("gym", 3), ("fitness", 3), ("workout", 3), ("trainer", 2),
                            ("membership", 2), ("exercise", 2), ("class schedule", 3),
                            ("weight", 1), ("cardio", 2), ("strength", 1), ("bench", 1),
                            ("locker", 2), ("personal trainer", 3), ("crossfit", 3),
                            ("yoga", 2), ("pilates", 2), ("sports club", 3)],
    "sports":              [("team", 2), ("match", 2), ("tournament", 3), ("season", 2),
                            ("league", 3), ("player", 2), ("score", 2), ("stadium", 3),
                            ("fixture", 3), ("referee", 2), ("coach", 2), ("sport", 1)],
    "hospitality":         [("hotel", 3), ("room", 2), ("booking", 2), ("checkin", 3),
                            ("checkout", 2), ("guest", 2), ("hostel", 3), ("resort", 3),
                            ("concierge", 3), ("housekeeping", 3), ("amenity", 2)],
    "real_estate":         [("property", 3), ("listing", 2), ("tenant", 3), ("lease", 3),
                            ("landlord", 3), ("rent", 2), ("mortgage", 3), ("agent", 2),
                            ("unit", 1), ("floor plan", 3), ("vacancy", 2)],
}
