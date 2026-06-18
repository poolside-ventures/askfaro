"""Client-side rendering and filtering for browse().

Shared by Faro and AsyncFaro so behavior is identical on both paths.
"""

from __future__ import annotations

from askfaro._capabilities import Capabilities


def budget_to_tier(budget: str | int) -> str:
    """Map an integer or named budget to the nearest server-side tier."""
    if isinstance(budget, str):
        return budget  # pass through; server validates named tiers
    if budget <= 4096:
        return "4k"
    return "32k"


def filter_manifest(manifest: dict, caps: Capabilities) -> dict:
    """Prune skill leaves the capability filter disallows, dropping now-empty
    categories. Returns the manifest unchanged when nothing is curated.

    Only direct skill leaves (nodes carrying `skill_id`) are filtered; namespace
    branch nodes are left intact.
    """
    if caps.is_empty:
        return manifest

    nodes: dict = manifest.get("nodes", {})
    root: dict = manifest.get("root", {})

    kept_nodes: dict = {}
    kept_cats: list[str] = []
    for cat_id in root.get("children", []):
        cat = nodes.get(cat_id)
        if not cat:
            continue
        kept_children: list[str] = []
        for child_id in cat.get("children", []):
            skill = nodes.get(child_id)
            if not skill:
                continue
            sid = skill.get("skill_id")
            if sid and not caps.allows(sid):
                continue
            kept_children.append(child_id)
            kept_nodes[child_id] = skill
        if kept_children:
            kept_nodes[cat_id] = {**cat, "children": kept_children}
            kept_cats.append(cat_id)

    return {**manifest, "root": {**root, "children": kept_cats}, "nodes": kept_nodes}


def render_manifest_text(manifest: dict, caps: Capabilities) -> str:
    """Render the (filtered) manifest as inject-ready markdown.

    Format:
        ## Category Title
        skill_id: what this skill does
    """
    m = filter_manifest(manifest, caps)
    nodes: dict = m.get("nodes", {})
    root: dict = m.get("root", {})

    lines: list[str] = []
    for cat_id in root.get("children", []):
        cat = nodes.get(cat_id)
        if not cat:
            continue
        skills = []
        for child_id in cat.get("children", []):
            skill = nodes.get(child_id)
            if not skill:
                continue
            sid = skill.get("skill_id") or child_id
            skills.append(f"{sid}: {skill.get('what', '')}")
        if skills:
            lines.append(f"## {cat.get('title', cat_id)}")
            lines.extend(skills)
            lines.append("")

    return "\n".join(lines).rstrip()
