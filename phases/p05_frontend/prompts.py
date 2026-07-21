"""P05 Frontend — domain detection data, prompt strings, and domain widget configs.

This module holds all the large data-driven dictionaries and prompt constants
used by the frontend code-generation phase agent.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from aether_os.phases.p05_frontend.design_system import get_design_tokens


def get_domain_color_hint(domain: str) -> str:
    """Convert the structured token dict for *domain* into the color-hint string
    format used in LLM prompts.  Existing callers in helpers.py can call this
    instead of reading DOMAIN_COLOR_HINTS directly.
    """
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

# ── Domain-specific stat-card labels ─────────────────────────────────────────
DOMAIN_STAT_LABELS: Dict[str, List[str]] = {
    "security":           ["Cameras Online", "Active Alerts", "Zones Monitored", "Incidents Today"],
    "iot":                ["Devices Online", "Active Sensors", "Alerts Today", "Avg Uptime %"],
    "healthcare":         ["Patients Today", "Appointments", "Avg Wait Time", "Staff On Duty"],
    "crm":                ["New Leads", "Open Deals", "Revenue This Month", "Conversion Rate"],
    "ecommerce":          ["Orders Today", "Revenue", "Items in Stock", "Cart Abandonment"],
    "library":            ["Books in Catalog", "Active Members", "Active Checkouts", "Overdue Items"],
    "hrm":                ["Headcount", "On Leave Today", "Open Positions", "Avg Tenure (yrs)"],
    "finance":            ["Invoices Due", "Revenue MTD", "Overdue Payments", "Burn Rate"],
    "project_management": ["Open Tasks", "Sprints Active", "PRs Merged", "Bugs Open"],
    "restaurant":         ["Tables Occupied", "Orders in Queue", "Avg Order Value", "Covers Today"],
    "education":          ["Enrolled Students", "Courses Active", "Avg Grade", "Attendance %"],
    "saas":               ["Active Users", "MRR", "Churn Rate", "NPS Score"],
    "gym_fitness":        ["Active Members", "Classes Today", "Check-ins Today", "Revenue MTD"],
    "sports":             ["Active Players", "Matches Today", "Teams Registered", "Tournaments"],
    "hospitality":        ["Rooms Occupied", "Check-ins Today", "Check-outs Today", "Revenue Today"],
    "real_estate":        ["Active Listings", "Vacant Units", "Leases Expiring", "Revenue MTD"],
}

# ── LLM-powered domain component generation ──────────────────────────────────
DOMAIN_COMPONENT_DESC: Dict[str, str] = {
    "security": (
        "a CameraGrid showing a 2×3 grid of camera feed placeholders, each with a camera name, "
        "zone badge (e.g. 'Zone A', 'Entrance'), status dot (Online=green, Offline=red, Alert=amber), "
        "and a mock timestamp. Include a top bar showing total cameras online (e.g. 94/100) and "
        "active alerts count with a red badge."
    ),
    "iot": (
        "a DeviceStatusPanel showing a list of 5 mock IoT devices with name, type badge "
        "(Sensor/Gateway/Actuator), last-seen timestamp, and a status pill (Online/Offline/Warning). "
        "Include a summary row at top with total online count and a blinking active indicator."
    ),
    "healthcare": (
        "a PatientVitals card showing mock vitals (Heart Rate: 72 bpm, BP: 120/80, SpO2: 98%) "
        "with coloured status badges and a compact appointment list for today"
    ),
    "crm": (
        "a DealPipeline kanban-style row with 4 columns (New, Contacted, Proposal, Closed) "
        "showing deal count and total value badges per column"
    ),
    "ecommerce": (
        "a ProductGrid showing 4 product cards with image placeholder, name, price, "
        "stock badge (In Stock / Low Stock / Out), and an Add-to-Cart button"
    ),
    "hrm": (
        "an AttendanceTracker showing a 5-day weekly grid for 5 mock employees "
        "with colour-coded cells (Present=green, Absent=red, Leave=yellow)"
    ),
    "finance": (
        "an InvoiceStatus panel showing a row of 3 summary tiles "
        "(Paid, Pending, Overdue) with amounts and a small recent-invoices list"
    ),
    "project_management": (
        "a KanbanBoard with 3 columns (Todo, In Progress, Done) "
        "each containing 2-3 task cards with priority badges and assignee avatars"
    ),
    "restaurant": (
        "a TableMap showing a 3×4 grid of table circles colour-coded by status "
        "(Free=green, Occupied=red, Reserved=yellow) with table numbers"
    ),
    "education": (
        "a GradeDistribution component showing a horizontal bar chart of grade bands "
        "(A/B/C/D/F) with student counts and a pass-rate summary"
    ),
    "saas": (
        "a MetricsDashboard showing 4 KPI tiles (Active Users, MRR, Churn Rate, NPS) "
        "each with a trend arrow (up/down) and a sparkline-style indicator row"
    ),
    "gym_fitness": (
        "a GymDashboard showing today's class schedule (4 classes with time, name, trainer, "
        "and slots-remaining badge), a member check-in counter, and a 7-day attendance sparkline"
    ),
    "sports": (
        "a MatchDayPanel showing today's fixtures (3 matches with home/away team, time, venue) "
        "and a standings mini-table with position, played, won, lost, points columns"
    ),
    "hospitality": (
        "a RoomStatusGrid showing 12 room cards in a 4×3 grid colour-coded by status "
        "(Available=green, Occupied=blue, Cleaning=yellow, Maintenance=red) with room number and type"
    ),
    "real_estate": (
        "a PropertyMap showing 6 listing cards with address, type badge (Apartment/House/Commercial), "
        "price, status pill (Available/Under Offer/Leased), and a thumbnail placeholder"
    ),
}

# ── Domain fallback widgets ───────────────────────────────────────────────────
DOMAIN_FALLBACK_WIDGETS: Dict[str, str] = {
    "crm": """
import React from 'react'
import { useQuery } from '@tanstack/react-query'
import { apiClient } from '../lib/api'

export default function DomainWidget() {
  const { data: stats, isLoading } = useQuery({
    queryKey: ['stats'],
    queryFn: () => apiClient.get('/stats').then(r => r.data),
    staleTime: 30_000,
  })

  const pipeline = [
    { stage: 'New', count: stats?.stage_new ?? 0 },
    { stage: 'Qualified', count: stats?.stage_qualified ?? 0 },
    { stage: 'Proposal', count: stats?.stage_proposal ?? 0 },
    { stage: 'Won', count: stats?.stage_won ?? 0 },
  ]

  if (isLoading) {
    return (
      <div className="p-6 bg-indigo-50 rounded-2xl animate-pulse">
        <div className="h-6 bg-indigo-200 rounded w-48 mb-4" />
        <div className="flex space-x-4">
          {[1,2,3,4].map(i => <div key={i} className="h-24 bg-indigo-100 rounded-xl w-1/4" />)}
        </div>
      </div>
    )
  }

  return (
    <div className="p-6 bg-indigo-50 rounded-2xl" role="region" aria-label="Deal pipeline overview">
      <h2 className="text-xl font-bold text-indigo-900 mb-4">Deal Pipeline</h2>
      <div className="flex space-x-4">
        {pipeline.map(({ stage, count }) => (
          <div key={stage}
            className="flex flex-col items-center bg-white border border-indigo-100 rounded-2xl shadow-sm p-4 flex-1"
            role="group" aria-label={`${stage} stage`}>
            <span className="text-xs font-bold uppercase tracking-widest text-indigo-500 mb-2">{stage}</span>
            <span className="text-3xl font-extrabold text-indigo-900">{count}</span>
            <span className="text-xs text-indigo-400 mt-1">Deals</span>
          </div>
        ))}
      </div>
    </div>
  )
}
""",
    "restaurant": "export default function DomainWidget() { return <div className='p-4 bg-white rounded-lg border'><h3>Table Map</h3><div className='grid grid-cols-4 gap-2 mt-2'>{[1,2,3,4,5,6,7,8].map(i => <div key={i} className='w-8 h-8 rounded-full bg-green-500 flex items-center justify-center text-white text-xs'>{i}</div>)}</div></div> }",
    "healthcare": "export default function DomainWidget() { return <div className='p-4 bg-white rounded-lg border'><h3>Today's Appointments</h3><ul className='mt-2 text-sm space-y-1'><li>9:00 AM - John Doe</li><li>10:30 AM - Jane Smith</li></ul></div> }",
    "ecommerce": "export default function DomainWidget() { return <div className='p-4 bg-white rounded-lg border'><h3>Sales Overview</h3><div className='mt-2 text-2xl font-bold'>$4,250.00</div><div className='text-xs text-green-600'>+12% from yesterday</div></div> }",
    "hrm": "export default function DomainWidget() { return <div className='p-4 bg-white rounded-lg border'><h3>Team Attendance</h3><div className='mt-2 flex gap-1'>{[1,2,3,4,5].map(i => <div key={i} className='w-2 h-8 bg-blue-500 rounded'></div>)}</div></div> }",
    "real_estate": "export default function DomainWidget() { return <div className='p-4 bg-white rounded-lg border'><h3>Property Map</h3><div className='aspect-video bg-gray-100 rounded mt-2 flex items-center justify-center text-gray-400'>Map View</div></div> }",
    "education": "export default function DomainWidget() { return <div className='p-4 bg-white rounded-lg border'><h3>Class Schedule</h3><div className='mt-2 space-y-2'><div className='h-2 bg-gray-100 rounded w-full'></div><div className='h-2 bg-gray-100 rounded w-3/4'></div></div></div> }",
    "gym_fitness": "export default function DomainWidget() { return <div className='p-4 bg-white rounded-lg border'><h3>Active Members</h3><div className='mt-2 text-3xl font-bold'>124</div></div> }",
    "hospitality": "export default function DomainWidget() { return <div className='p-4 bg-white rounded-lg border'><h3>Room Status</h3><div className='grid grid-cols-5 gap-1 mt-2'>{[1,2,3,4,5].map(i => <div key={i} className='h-4 bg-green-500 rounded'></div>)}</div></div> }",
    "logistics": "export default function DomainWidget() { return <div className='p-4 bg-white rounded-lg border'><h3>Fleet Tracking</h3><div className='mt-2 space-y-1 text-xs'><div>Truck 01: En Route</div><div>Truck 02: Loading</div></div></div> }",
    "marketplace": "export default function DomainWidget() { return <div className='p-4 bg-white rounded-lg border'><h3>Top Sellers</h3><div className='mt-2 space-y-2'>{[1,2,3].map(i => <div key={i} className='h-4 bg-gray-50 rounded'></div>)}</div></div> }",
    "saas": "export default function DomainWidget() { return <div className='p-4 bg-white rounded-lg border'><h3>MRR Trend</h3><div className='mt-2 h-16 flex items-end gap-1'>{[4,6,5,8,7].map(i => <div key={i} style={{height: `${i*10}%`}} className='bg-indigo-500 w-full rounded-t'></div>)}</div></div> }",
    "fintech": "export default function DomainWidget() { return <div className='p-4 bg-white rounded-lg border'><h3>Cash Flow</h3><div className='mt-2 text-xl font-mono'>$128,450.00</div></div> }",
    "library": "export default function DomainWidget() { return <div className='p-4 bg-white rounded-lg border'><h3>Checked Out</h3><div className='mt-2 text-2xl font-bold'>42 Books</div></div> }",
    "security": "export default function DomainWidget() { return <div className='p-4 bg-white rounded-lg border'><h3>System Health</h3><div className='mt-2 text-green-600 font-bold'>ALL SYSTEMS NOMINAL</div></div> }",
    "iot": "export default function DomainWidget() { return <div className='p-4 bg-white rounded-lg border'><h3>Device Feed</h3><div className='mt-2 space-y-1'>{[1,2].map(i => <div key={i} className='h-2 bg-blue-400 rounded'></div>)}</div></div> }",
    "events": "export default function DomainWidget() { return <div className='p-4 bg-white rounded-lg border'><h3>Ticket Sales</h3><div className='mt-2 text-lg font-bold'>85% Capacity</div></div> }",
    "sports": "export default function DomainWidget() { return <div className='p-4 bg-white rounded-lg border'><h3>Latest Scores</h3><div className='mt-2 text-sm'>Team A 2 - 1 Team B</div></div> }",
}

# ── Domain-appropriate colour palette hints ────────────────────────────────────
DOMAIN_COLOR_HINTS: Dict[str, str] = {
    "healthcare":   "teal palette: bg-teal-50/100, text-teal-800/900, borders teal-200, accents teal-600",
    "fintech":      "dark navy-gold: bg-slate-900, text-yellow-300, cards bg-slate-800, accents yellow-400",
    "ecommerce":    "rose-pink: bg-rose-50, text-rose-900, cards bg-white border-rose-100, accents rose-600",
    "marketplace":  "violet: bg-violet-50, text-violet-900, cards bg-white border-violet-100, accents violet-600",
    "education":    "sky-cyan: bg-sky-50, text-sky-900, cards bg-white border-sky-100, accents sky-600",
    "gym_fitness":  "red-energy: bg-red-50, text-red-900, cards bg-white border-red-100, accents red-600",
    "fitness":      "red-energy: bg-red-50, text-red-900, cards bg-white border-red-100, accents red-600",
    "real_estate":  "emerald: bg-emerald-50, text-emerald-900, cards bg-white border-emerald-100, accents emerald-600",
    "hospitality":  "amber-warm: bg-amber-50, text-amber-900, cards bg-white border-amber-100, accents amber-600",
    "restaurant":   "orange-warm: bg-orange-50, text-orange-900, cards bg-white border-orange-100, accents orange-600",
    "food":         "orange-warm: bg-orange-50, text-orange-900, cards bg-white border-orange-100, accents orange-600",
    "logistics":    "slate-blue: bg-slate-50, text-slate-900, cards bg-white border-slate-200, accents slate-600",
    "iot":          "slate-blue: bg-slate-900, text-cyan-300, cards bg-slate-800, accents cyan-400",
    "hrm":          "indigo: bg-indigo-50, text-indigo-900, cards bg-white border-indigo-100, accents indigo-600",
    "crm":          "indigo: bg-indigo-50, text-indigo-900, cards bg-white border-indigo-100, accents indigo-600",
    "analytics":    "indigo: bg-indigo-50, text-indigo-900, cards bg-white border-indigo-100, accents indigo-600",
    "saas":         "violet-purple: bg-violet-50, text-violet-900, cards bg-white border-violet-100, accents violet-600",
    "security":     "slate-red: bg-slate-900, text-red-300, cards bg-slate-800 border-slate-700, accents red-500",
    "sports":       "green-energy: bg-green-50, text-green-900, cards bg-white border-green-100, accents green-600",
    "library":      "stone: bg-stone-50, text-stone-900, cards bg-white border-stone-200, accents amber-700",
}

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

# ── Theme CSS snippets ─────────────────────────────────────────────────────────
THEME_CSS: Dict[str, str] = {
    "glassmorphism": """\
/* Glassmorphism theme */
body { background: linear-gradient(135deg, #4f46e5 0%, #7c3aed 50%, #db2777 100%) fixed; min-height: 100vh; }
.glass-card { background: rgba(255,255,255,0.12); backdrop-filter: blur(16px) saturate(180%); -webkit-backdrop-filter: blur(16px) saturate(180%); border: 1px solid rgba(255,255,255,0.25); box-shadow: 0 8px 32px rgba(0,0,0,0.2); }
""",
    "neomorphism": """\
/* Neomorphism theme */
body { background: #e0e5ec; color: #4b5563; }
.neo-card { background: #e0e5ec; border-radius: 12px; box-shadow: 6px 6px 12px #a3b1c6, -6px -6px 12px #ffffff; border: none; }
.neo-inset { box-shadow: inset 4px 4px 8px #a3b1c6, inset -4px -4px 8px #ffffff; }
.neo-btn { background: #e0e5ec; border-radius: 8px; box-shadow: 4px 4px 8px #a3b1c6, -4px -4px 8px #ffffff; border: none; }
.neo-btn:active { box-shadow: inset 2px 2px 5px #a3b1c6, inset -2px -2px 5px #ffffff; }
""",
    "material": """\
/* Material Design 3 theme */
body { background: #fffbfe; color: #1c1b1f; font-family: 'Roboto', 'Google Sans', sans-serif; }
.md-surface { background: #f3edf7; border-radius: 12px; }
.md-surface-variant { background: #e7e0ec; }
.md-primary { background: #6750a4; color: #ffffff; border-radius: 100px; }
.md-secondary { background: #625b71; color: #ffffff; border-radius: 100px; }
.md-elevation-1 { box-shadow: 0 1px 2px rgba(0,0,0,0.3), 0 1px 3px 1px rgba(0,0,0,0.15); }
.md-elevation-2 { box-shadow: 0 1px 2px rgba(0,0,0,0.3), 0 2px 6px 2px rgba(0,0,0,0.15); }
.md-ripple { position: relative; overflow: hidden; }
""",
    "flat": """\
/* Flat / Minimal theme */
body { background: #ffffff; color: #111827; }
* { box-shadow: none !important; }
.flat-card { background: #f9fafb; border: 1px solid #e5e7eb; border-radius: 0; }
.flat-btn { border-radius: 0; border: 2px solid #111827; background: #111827; color: #ffffff; }
.flat-btn-outline { border-radius: 0; border: 2px solid #111827; background: transparent; color: #111827; }
""",
    "brutalist": """\
/* Brutalist theme */
body { background: #ffffff; color: #000000; font-family: 'Courier New', monospace; }
* { border-radius: 0 !important; }
.brut-card { background: #ffffff; border: 2px solid #000000; box-shadow: 4px 4px 0 #000000; }
.brut-card:hover { box-shadow: 6px 6px 0 #000000; transform: translate(-2px,-2px); }
.brut-btn { background: #000000; color: #ffffff; border: 2px solid #000000; padding: 8px 16px; box-shadow: 3px 3px 0 #f97316; }
.brut-btn:hover { box-shadow: 5px 5px 0 #f97316; transform: translate(-2px,-2px); }
.brut-accent { background: #facc15; color: #000000; }
""",
    "neon_cyberpunk": """\
/* Neon / Cyberpunk theme */
body { background: #050810; color: #e2e8f0; font-family: 'Share Tech Mono', 'Courier New', monospace; }
body::before { content:''; position:fixed; inset:0; background-image: linear-gradient(rgba(0,255,255,0.03) 1px,transparent 1px), linear-gradient(90deg,rgba(0,255,255,0.03) 1px,transparent 1px); background-size: 40px 40px; pointer-events:none; z-index:0; }
.cyber-card { background: rgba(5,8,16,0.85); border: 1px solid #00ffff; box-shadow: 0 0 12px rgba(0,255,255,0.25), inset 0 0 12px rgba(0,255,255,0.05); }
.cyber-card-magenta { border-color: #ff00ff; box-shadow: 0 0 12px rgba(255,0,255,0.25), inset 0 0 12px rgba(255,0,255,0.05); }
.cyber-text-glow { color: #00ffff; text-shadow: 0 0 8px #00ffff; }
.cyber-btn { background: transparent; border: 1px solid #00ffff; color: #00ffff; box-shadow: 0 0 8px rgba(0,255,255,0.4); }
.cyber-btn:hover { background: rgba(0,255,255,0.1); box-shadow: 0 0 16px rgba(0,255,255,0.6); }
""",
    "soft_pastel": """\
/* Soft Pastel theme */
body { background: #fdf4ff; color: #3b1f5e; font-family: 'Nunito', 'Inter', sans-serif; }
.pastel-card { background: #fce7f3; border: 1px solid #fbcfe8; border-radius: 16px; box-shadow: 0 4px 20px rgba(168,85,247,0.08); }
.pastel-card-blue { background: #e0f2fe; border-color: #bae6fd; }
.pastel-card-green { background: #dcfce7; border-color: #bbf7d0; }
.pastel-btn { background: #a855f7; color: #ffffff; border-radius: 50px; box-shadow: 0 4px 12px rgba(168,85,247,0.3); }
.pastel-btn:hover { background: #9333ea; box-shadow: 0 6px 16px rgba(168,85,247,0.4); transform: translateY(-1px); }
""",
}

SPEED_MS: Dict[str, int] = {
    "instant": 0, "fast": 150, "normal": 300, "slow": 500, "cinematic": 800,
}

TRANSITION_CSS: Dict[str, str] = {
    "fade":  "transition: opacity {ms}ms ease;",
    "slide": "transition: transform {ms}ms ease, opacity {ms}ms ease;",
    "scale": "transition: transform {ms}ms cubic-bezier(.4,0,.2,1), opacity {ms}ms ease;",
    "flip":  "transition: transform {ms}ms ease; transform-style: preserve-3d;",
    "blur":  "transition: filter {ms}ms ease, opacity {ms}ms ease;",
}

SKELETON_CSS: Dict[str, str] = {
    "pulse":   ".skeleton { animation: pulse 1.5s cubic-bezier(.4,0,.6,1) infinite; background: rgba(148,163,184,.2); border-radius:4px; } @keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}",
    "shimmer": ".skeleton { background: linear-gradient(90deg,rgba(148,163,184,.1) 25%,rgba(148,163,184,.25) 50%,rgba(148,163,184,.1) 75%); background-size:200% 100%; animation:shimmer 1.5s infinite; border-radius:4px; } @keyframes shimmer{0%{background-position:200% 0}100%{background-position:-200% 0}}",
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
