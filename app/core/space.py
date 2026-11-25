"""Where the space went: a tree of folder sizes, and the forgotten files in
Downloads. Pure: `io/cleaner.py` walks, this adds up.

One walk of a whole profile can meet a million files, so the tree keeps
nodes only `DEPTH` levels down; everything deeper is added into its ancestor
at that depth. Enough to find the folder that matters, and the tree stays a
few thousand nodes.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

DEPTH = 6


@dataclass
class Node:
    name: str
    path: str
    size: int = 0
    files: int = 0
    children: dict[str, "Node"] = field(default_factory=dict)

    def sorted_children(self) -> list["Node"]:
        return sorted(self.children.values(), key=lambda n: n.size, reverse=True)


def add(root: Node, parts: list[str], size: int, *, sep: str = "\\") -> None:
    """Count one file of `size` whose folder is `parts` below `root`."""
    node = root
    node.size += size
    node.files += 1
    for depth, part in enumerate(parts):
        if depth >= DEPTH:
            break
        child = node.children.get(part)
        if child is None:
            child = Node(part, node.path.rstrip(sep) + sep + part)
            node.children[part] = child
        child.size += size
        child.files += 1
        node = child


@dataclass
class Forgotten:
    path: str
    size: int
    modified: float
    why: str


def forgotten(files: list[tuple[str, int, float]], *, now: float | None = None,
              big: int = 100 * 1024 * 1024, old_days: int = 90,
              old_min: int = 10 * 1024 * 1024) -> list[Forgotten]:
    """Files in Downloads worth a look: very large ones, and middling ones
    nobody has touched in months. Largest first."""
    now = time.time() if now is None else now
    out = []
    for path, size, modified in files:
        age = (now - modified) / 86400
        if size >= big:
            why = "Large"
        elif size >= old_min and age >= old_days:
            why = f"Not changed in {int(age)} days"
        else:
            continue
        out.append(Forgotten(path, size, modified, why))
    return sorted(out, key=lambda f: f.size, reverse=True)
