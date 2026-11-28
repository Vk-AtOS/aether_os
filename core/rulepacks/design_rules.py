"""Design prompt rule pack: short numbered rules per site type, for LLM page prompts.

    design_prompt_rules("booking", tokens)   # -> compact string, <= ~1200 tokens

The rules are written for a small model: imperative, one idea per line, numbered so a repair prompt can say
"rule 7". Wording is AetherOS's own (see NOTICE.md for the public sources of the ideas).
"""
from __future__ import annotations

from aether_os.core.rulepacks.design_catalog import PROFILES, canonical_site_type
from aether_os.core.rulepacks.design_tokens import DesignTokens

LAYOUT = {
    "landing": (
        "Section order: hero (headline of 12 words or fewer, one supporting sentence, one primary CTA, a real "
        "product visual) > proof (logos or a number) > 3-5 benefits in alternating layouts > how it works (only "
        "if the steps are truly sequential) > testimonials > pricing if relevant > FAQ > closing CTA > footer.",
        "Show the primary CTA above the fold and repeat it after the proof section. Section padding py-16 or more "
        "on desktop; content width max-w-6xl, gutters px-4 / md:px-8.",
    ),
    "saas_dashboard": (
        "Shell: collapsible left sidebar + top bar. Each page: title and actions row, then up to 4 KPI tiles, "
        "then the main table or chart, then secondary panels.",
        "Dense but calm: 14px base text, neutral surfaces, one accent. Tables get a sticky header, row hover, "
        "filters above, pagination below. Charts use the chart-1..5 tokens, a legend and tooltips.",
    ),
    "ecommerce": (
        "Home: hero with one featured collection > category tiles > best sellers grid > trust row (shipping, "
        "returns, secure payment) > footer. Product grid cards share one image aspect ratio.",
        "Product page: gallery left, title, price (most prominent text after the title), variant pickers, sticky "
        "add-to-cart on mobile, details accordion, reviews. Use urgency and sale colors sparingly.",
    ),
    "booking": (
        "Home: hero stating the service and area + 'Book now' CTA > services with duration and price > how "
        "booking works (3 steps) > team or practitioner cards > reviews > opening hours, map, contact > footer.",
        "The booking flow is one column (max-w-md): service > date and time slot > details > confirm. Show the "
        "chosen slot at every step; disabled slots are visibly unavailable, not hidden.",
    ),
    "content": (
        "Article layout: header (title, author, date, reading time) > body in a 65ch column (max-w-prose) > "
        "related posts. Index: featured post + a list with title, excerpt, date; tags filter.",
        "Type leads: 18px body, line-height 1.6+, strong heading hierarchy, code blocks with a copy button, "
        "images with captions. Docs add a left nav and a right table of contents on wide screens.",
    ),
    "portfolio": (
        "Home: name + one-line positioning > selected work grid (varied aspect ratios, image-first) > about > "
        "contact. Case study: problem > role > process images > outcome with numbers.",
        "Let typography and whitespace carry the page; one signature detail (a cursor, a transition or a type "
        "treatment) used consistently beats many effects.",
    ),
    "internal_tool": (
        "Shell: sidebar navigation + content area. Each page: title, primary action button, filters, then a "
        "data table with pagination; forms open in a side sheet or a dedicated page.",
        "Optimise for speed of use: 14px base, compact rows, keyboard-friendly forms, clear status badges. "
        "No marketing sections, hero images or decorative illustrations.",
    ),
    "agent_chat": (
        "Layout: conversation list (left, collapsible) > message thread (center, max-w-3xl) > composer pinned "
        "to the bottom. Optional right panel for sources, tools or run details.",
        "Messages: user right / assistant left, markdown rendered safely, code blocks with copy, a visible "
        "streaming indicator, a stop button while generating, retry on error, and suggested first prompts.",
    ),
}

COMMON = (
    "Use only the design tokens: Tailwind classes bg-background, text-foreground, bg-primary, "
    "text-primary-foreground, text-muted-foreground, border-border, bg-card, bg-accent, ring-ring, "
    "bg-destructive. No hex, rgb() or raw palette classes such as bg-blue-500 in components.",
    "Spacing comes from the 4px grid (p-1=4px, p-2=8px, p-4=16px, p-6, p-8, p-12, p-16). No arbitrary values "
    "such as p-[13px]. Group related items by proximity before adding borders or dividers.",
    "Hierarchy: one h1 per page and no skipped heading levels; one filled primary button per view, the rest "
    "outline or ghost; size and weight make hierarchy, not extra colors.",
    "Every view that loads data renders four states: loading (skeleton shaped like the content), empty (says "
    "what is missing and offers the next action), error (what happened, plus a retry), and success.",
    "Accessibility: every img has alt (alt=\"\" if decorative); icon-only buttons have aria-label; every input "
    "has a visible <label> tied by htmlFor/id (placeholder is not a label); clickable things are <button> or "
    "<a>, never a div with onClick; keep focus-visible rings; color is never the only signal.",
    "Text contrast is already AA in the tokens; do not put muted text on colored backgrounds or text over "
    "photos without an overlay.",
    "Copy: real, specific words for this business. Sentence case. Buttons are verb + object (\"Book a visit\", "
    "not \"Submit\"). Errors say what happened and how to fix it.",
    "Mobile first: works at 375px with no horizontal scroll; touch targets at least 44px tall; grids collapse "
    "to one column.",
    "Images: set width and height or an aspect-ratio class; loading=\"lazy\" below the fold.",
)

SLOP = (
    "Avoid the generic generated look. Do not use: violet/indigo-to-pink gradients; gradient text on headings; "
    "a 3-card feature grid with an icon in a rounded square on every section; an ALL-CAPS eyebrow over every "
    "heading; one highlighted word in every headline; arrows on every link; emoji as icons; the same shadow "
    "on every card; fade-up animation on every section.",
    "Never ship placeholder copy: no lorem ipsum, John Doe, Acme, Feature One, Your Company, example.com links, "
    "\"Revolutionize\", \"Seamless\", \"Unlock the power of\", \"Elevate your\", \"All-in-one platform\".",
)


def design_prompt_rules(site_type: str, tokens: DesignTokens | None = None) -> str:
    """Numbered design rules for one site type, plus a one-line token summary when tokens are given."""
    st = canonical_site_type(site_type)
    prof = PROFILES[st]
    rules = list(LAYOUT[st]) + list(COMMON)
    rules.append(f"Motion budget: {prof.motion}. Animate only opacity and transform, 100-300ms, and honour "
                 "prefers-reduced-motion (motion-reduce: variants).")
    rules += list(SLOP)
    head = [f"DESIGN RULES ({st.replace('_', ' ')}). Follow every rule; they are checked after generation."]
    if tokens is not None:
        head.append(f"Fonts: headings font-heading ({tokens.fonts.heading}), body font-sans ({tokens.fonts.body}); "
                    f"no other families. Radius: rounded-md for controls, rounded-lg for cards. "
                    f"Shadows: shadow-sm / shadow-md / shadow-lg only.")
    return "\n".join(head + [f"{i}. {r}" for i, r in enumerate(rules, 1)])
