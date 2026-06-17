"""Client-side rendering for browse(format='text').

Shared by Faro and AsyncFaro so the rendering is identical on both paths.
"""

from __future__ import annotations


def budget_to_tier(budget: str | int) -> str:
    """Map an integer or named budget to the nearest server-side tier."""
    if isinstance(budget, str):
        return budget  # pass through; server validates named tiers
    if budget <= 4096:
        return "4k"
    return "32k"


def render_manifest_text(manifest: dict, exclude: frozenset[str]) -> str:
    """Render the manifest as inject-ready markdown.

    Format:
        ## Category Title
        skill_id: what this skill does
    """
    nodes: dict = manifest.get("nodes", {})
    root: dict = manifest.get("root", {})

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
            sid: str = skill.get("skill_id") or child_id
            if sid in exclude:
                continue
            skills.append(f"{sid}: {skill.get('what', '')}")
        if skills:
            lines.append(f"## {cat.get('title', cat_id)}")
            lines.extend(skills)
            lines.append("")

    return "\n".join(lines).rstrip()
