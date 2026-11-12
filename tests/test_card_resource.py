"""Tests for the Lovelace resource plan of the bundled dashboard card."""

from __future__ import annotations

import json
from pathlib import Path

from custom_components.myorlen_ebok.card_resource import (
    ResourcePlan,
    base_url,
    plan_card_resource,
    resource_payload,
)

URL = "/myorlen_ebok/myorlen-ebok-card.js?v=0.3.0-abcdef12"
COMPONENT = Path(__file__).parent.parent / "custom_components" / "myorlen_ebok"


def _item(item_id: str, url: str, res_type: str = "module") -> dict[str, str]:
    return {"id": item_id, "url": url, "type": res_type}


def test_creates_the_resource_on_a_fresh_install() -> None:
    others = [_item("a", "/local/community/mushroom/mushroom.js?v=1")]
    assert plan_card_resource(others, URL) == ResourcePlan(create=True)
    assert plan_card_resource([], URL).create


def test_leaves_an_up_to_date_resource_alone() -> None:
    assert plan_card_resource([_item("a", URL)], URL).unchanged


def test_updates_the_existing_resource_for_a_new_version() -> None:
    old = _item("a", "/myorlen_ebok/myorlen-ebok-card.js?v=0.2.9-00000000")
    assert plan_card_resource([old], URL) == ResourcePlan(update_id="a")


def test_fixes_a_wrong_resource_type() -> None:
    assert plan_card_resource([_item("a", URL, "js")], URL).update_id == "a"


def test_removes_duplicates_and_keeps_the_first() -> None:
    items = [_item("a", URL), _item("b", "/myorlen_ebok/myorlen-ebok-card.js")]
    assert plan_card_resource(items, URL) == ResourcePlan(delete_ids=["b"])


def test_ignores_other_cards_and_a_manual_copy_elsewhere() -> None:
    items = [
        _item("a", "/local/myorlen-ebok-card/myorlen-ebok-card.js?v=0.1.0"),
        _item("b", "/myorlen_ebok/other.js"),
    ]
    assert plan_card_resource(items, URL) == ResourcePlan(create=True)


def test_payload_and_base_url() -> None:
    assert resource_payload(URL) == {"url": URL, "res_type": "module"}
    assert base_url(URL) == "/myorlen_ebok/myorlen-ebok-card.js"
    assert base_url("/x.js") == "/x.js"


def test_the_card_bundle_ships_with_the_integration() -> None:
    bundle = COMPONENT / "frontend" / "myorlen-ebok-card.js"
    version = json.loads((COMPONENT / "manifest.json").read_text())["version"]
    assert bundle.is_file()
    # The bundle logs the integration version it was built for.
    assert f"MYORLEN-EBOK-CARD %c {version} " in bundle.read_text(encoding="utf-8")
