from dataclasses import replace
import random

import pytest

from irestock_demo.domain import Dataset, StockRow
from irestock_demo.transfer import transfer


def row(store: str, **changes) -> StockRow:
    values = dict(sku="SKU-1", style="STYLE-1", store=store, store_brand="BRAND-A", sales_30d=8, sales_90d=20)
    values.update(changes)
    return StockRow(**values)


def test_same_brand_only_and_donor_retains_target():
    data = Dataset((row("DONOR", stock=10), row("TARGET"), row("OTHER", store_brand="BRAND-B", main_push=True)), {})
    result = transfer(data)
    assert result["moves"] == [{
        "sku": "SKU-1", "source": "DONOR", "target": "TARGET", "quantity": 4,
        "store_brand": "BRAND-A", "rule_id": "T001", "reason": "Same-brand surplus above donor target",
    }]
    donor = next(item for item in result["balances"] if item["store"] == "DONOR")
    assert donor["after"] == 6 and donor["retained_target"] == 4


def test_main_push_receiver_wins_limited_surplus():
    result = transfer(Dataset((row("DONOR", stock=9), row("MAIN", main_push=True), row("SECOND")), {}))
    assert [(item["target"], item["quantity"]) for item in result["moves"]] == [("MAIN", 4), ("SECOND", 1)]
    assert all(item["source"] != item["target"] for item in result["moves"])


def test_blocked_target_has_null_quantity_and_real_rule_evidence():
    result = transfer(Dataset((row("DONOR", stock=20), row("PENDING", in_order=1)), {}))
    assert not result["moves"]
    target = next(item for item in result["audit"] if item["store"] == "PENDING")
    assert target["target_stock"] is None and target["unfilled_qty"] is None
    assert target["trace"][0]["rule_id"] == "G001"


def test_unsupported_constraint_fails_instead_of_silently_ignoring_it():
    with pytest.raises(ValueError, match="does not support"):
        transfer(Dataset((row("A"), row("B")), {}, avoidance=(("A", "B"),)))


def test_random_transfer_conserves_inventory_and_never_exceeds_donor_budget():
    randomizer = random.Random(875)
    for _ in range(100):
        rows = tuple(row(str(index), stock=randomizer.randrange(15), sales_30d=randomizer.randrange(14),
                         store_brand=f"BRAND-{index % 2}") for index in range(8))
        data = Dataset(rows, {})
        result = transfer(data)
        assert result == transfer(replace(data, rows=tuple(reversed(rows))))
        assert sum(item["before"] for item in result["balances"]) == sum(item["after"] for item in result["balances"])
        for item in result["balances"]:
            assert item["after"] >= 0
            if item["out"]:
                assert item["after"] >= item["retained_target"]
