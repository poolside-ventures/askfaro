"""Catalog filtering + budget-bounded rendering for browse().

Size control is delegated to the progressive-context library (`Runtime`): we
disclose categories -> skills greedily within a real token budget, rather than
char-trimming a flat dump. PCX owns the budget accounting; this module owns the
Faro-specific rendering (showing each node's `skill_id`, carried in node `meta`).
"""

from __future__ import annotations

from askfaro._capabilities import Capabilities

_NAMED_BUDGETS = {"4k": 4096, "32k": 32768}


def budget_to_tier(budget: str | int) -> str:
    """Map an integer or named budget to the nearest server-side variant to fetch."""
    if isinstance(budget, str):
        return budget  # pass through; server validates named tiers
    return "4k" if budget <= 4096 else "32k"


def budget_to_tokens(budget: str | int) -> int:
    """The token ceiling navigation should respect."""
    if isinstance(budget, int):
        return budget
    return _NAMED_BUDGETS.get(budget, 4096)


def filter_manifest(manifest: dict, caps: Capabilities) -> dict:
    """Prune skill leaves the capability filter disallows, dropping now-empty
    categories. Branch (namespace) children are kept with their whole subtree so
    the tree stays navigable. Returns the manifest unchanged when nothing is curated.
    """
    if caps.is_empty:
        return manifest

    nodes: dict = manifest.get("nodes", {})
    root: dict = manifest.get("root", {})
    kept_nodes: dict = {}

    def keep_subtree(nid: str) -> None:
        node = nodes.get(nid)
        if not node:
            return
        kept_nodes[nid] = node
        for child in node.get("children", []):
            keep_subtree(child)

    kept_cats: list[str] = []
    for cat_id in root.get("children", []):
        cat = nodes.get(cat_id)
        if not cat:
            continue
        kept_children: list[str] = []
        for child_id in cat.get("children", []):
            node = nodes.get(child_id)
            if not node:
                continue
            sid = node.get("skill_id")
            if sid and not caps.allows(sid):
                continue
            kept_children.append(child_id)
            if sid:
                kept_nodes[child_id] = node
            else:
                keep_subtree(child_id)  # namespace branch: keep its subtree
        if kept_children:
            kept_nodes[cat_id] = {**cat, "children": kept_children}
            kept_cats.append(cat_id)

    return {**manifest, "root": {**root, "children": kept_cats}, "nodes": kept_nodes}


def render_budget_text(manifest: dict, budget_tokens: int, caps: Capabilities) -> str:
    """An inject-ready markdown catalog disclosed as deeply as `budget_tokens`
    allows. Categories that fit have their skills listed (`skill_id: what`);
    categories that don't are left as openable headers. Budget-bounded by PCX's
    own token accounting — no content is truncated.
    """
    from askfaro_progressive_context import Manifest, Runtime

    m = Manifest.from_dict(filter_manifest(manifest, caps))
    # `brief` descriptor accounting (title + what) matches what we render
    # (`skill_id: what`), so the budget isn't spent on `when`/keywords we omit.
    rt = Runtime(m, budget=budget_tokens, view_level="brief")

    sections: list[str] = []
    overflow: list[str] = []
    for entry in rt.peek():  # top-level frontier == categories
        if entry.is_leaf:
            continue
        title = entry.title or entry.node_id
        if entry.expand_cost <= rt.budget_remaining:
            children = rt.expand(entry.node_id)  # reveal skills, charge the budget
            lines = [f"## {title}"]
            for c in children:
                sid = c.meta.get("skill_id") or c.node_id
                lines.append(f"{sid}: {c.what}")
            if len(lines) > 1:
                sections.append("\n".join(lines))
        else:
            overflow.append(f"- {title}: open '{entry.node_id}'")

    text = "\n\n".join(sections)
    if overflow:
        more = "## More — open to reveal\n" + "\n".join(overflow)
        text = f"{text}\n\n{more}" if text else more
    return text
