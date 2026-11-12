"""Decide what to do with the Lovelace resource of the bundled dashboard card.

Kept free of Home Assistant imports so the decision can be tested on its own.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

RESOURCE_TYPE = "module"


@dataclass(frozen=True)
class ResourcePlan:
    """Changes that leave exactly one resource pointing at the card bundle."""

    create: bool = False
    update_id: str | None = None
    delete_ids: list[str] = field(default_factory=list)

    @property
    def unchanged(self) -> bool:
        """Return whether the stored resources are already right."""
        return not self.create and self.update_id is None and not self.delete_ids


def base_url(url: str) -> str:
    """Return a resource URL without its cache-busting query string."""
    return url.partition("?")[0]


def plan_card_resource(items: Iterable[Mapping[str, Any]], versioned_url: str) -> ResourcePlan:
    """Plan the resource changes for the card served at `versioned_url`.

    Resources are matched on the path alone, so a new version updates the row
    that is already there instead of adding one next to it. Extra rows for the
    same path (left by an earlier bug or a manual add) are removed.
    """
    target = base_url(versioned_url)
    matches = [
        item for item in items if base_url(str(item.get("url", ""))) == target and item.get("id")
    ]
    if not matches:
        return ResourcePlan(create=True)
    keep, *extra = matches
    up_to_date = keep.get("url") == versioned_url and keep.get("type") == RESOURCE_TYPE
    return ResourcePlan(
        update_id=None if up_to_date else str(keep["id"]),
        delete_ids=[str(item["id"]) for item in extra],
    )


def resource_payload(versioned_url: str) -> dict[str, str]:
    """Return the data Lovelace's resource collection takes for the card."""
    return {"url": versioned_url, "res_type": RESOURCE_TYPE}
