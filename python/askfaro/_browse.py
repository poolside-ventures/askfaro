"""Client-side rendering for browse(format='text').

Shared by Faro and AsyncFaro so the rendering guarantee is identical on both paths.
"""

from __future__ import annotations

_BUDGET_TIERS: dict[str, int] = {
    "4k": 4096,
    "32k": 32768,
}


def budget_to_tier(budget: str | int) -> str:
    """Map an integer or named budget to the nearest available server-side tier."""
    if isinstance(budget, str):
        return budget  # pass through; server validates named tiers
    if budget <= 4096:
        return "4k"
    return "32k"


def budget_to_tokens(budget: str | int) -> int:
    """Return the token ceiling for rendered-text trimming."""
    if isinstance(budget, int):
        return budget
    return _BUDGET_TIERS.get(budget, 4096)


def _count_tokens(text: str) -> int:
    # 1 token ≈ 4 chars; ceiling so we never claim to fit when we don't.
    return (len(text) + 3) // 4


def render_manifest_text(
    manifest: dict,
    budget_tokens: int,
    exclude: frozenset[str],
) -> str:
    """Render the manifest as inject-ready markdown.

    Format:
        ## Category Title
        skill_id: what this skill does

    Trims progressively to guarantee the returned text is ≤ budget_tokens
    (by the chars/4 approximation used throughout the SDK).
    """
    nodes: dict = manifest.get("nodes", {})
    root: dict = manifest.get("root", {})

    # Walk tree: root -> category branches -> skill leaves
    categories: list[tuple[str, list[tuple[str, str, str]]]] = []
    for cat_id in root.get("children", []):
        cat = nodes.get(cat_id)
        if not cat:
            continue
        cat_title: str = cat.get("title", cat_id)
        skills: list[tuple[str, str, str]] = []
        for child_id in cat.get("children", []):
            skill = nodes.get(child_id)
            if not skill:
                continue
            sid: str = skill.get("skill_id") or child_id
            if sid in exclude:
                continue
            what: str = skill.get("what", "")
            title: str = skill.get("title", sid)
            skills.append((sid, title, what))
        if skills:
            categories.append((cat_title, skills))

    # Progressive trimming: full what -> titles only -> ids only -> drop categories
    for level in ("full", "title", "ids"):
        text = _render_at_level(categories, level)
        if _count_tokens(text) <= budget_tokens:
            return text

    # Still over budget: shed trailing categories until we fit
    for n in range(len(categories) - 1, 0, -1):
        text = _render_at_level(categories[:n], "ids")
        if _count_tokens(text) <= budget_tokens:
            return text

    return _render_at_level(categories[:1], "ids")


def _render_at_level(
    categories: list[tuple[str, list[tuple[str, str, str]]]], level: str
) -> str:
    lines: list[str] = []
    for cat_title, skills in categories:
        lines.append(f"## {cat_title}")
        for sid, title, what in skills:
            if level == "full":
                lines.append(f"{sid}: {what}")
            elif level == "title":
                lines.append(f"{sid}: {title}")
            else:
                lines.append(sid)
        lines.append("")
    return "\n".join(lines).rstrip()
