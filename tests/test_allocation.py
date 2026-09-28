from dataclasses import replace
import random

import pytest

from irestock_demo.allocation import replenish
from irestock_demo.domain import Dataset, Policy, StockRow
from irestock_demo.rules import IncomingStockGate, RuleRegistry, SalesCoverageTarget


def row(store: str, **changes) -> StockRow:
    values = dict(sku="SKU-1", style="STYLE-1", store=store, store_brand="BRAND-A", sales_30d=8, sales_90d=20)
    values.update(changes)
    return StockRow(**values)


def allocated(result: dict) -> dict:
    return {(item["sku"], item["store"]): item["quantity"] for item in result["allocations"]}


@pytest.mark.parametrize("flag", ["in_order", "in_transit"])
def test_pending_stock_is_terminal_before_quantity(flag):
    result = replenish(Dataset((row("A", **{flag: 1}),), {"SKU-1": 100}))
    audit = result["audit"][0]
    assert result["allocations"] == []
    assert audit["target_stock"] is None and audit["requested_qty"] is None
    assert [decision["rule_id"] for decision in audit["trace"]] == ["G001"]


def test_phase_order_does_not_depend_on_registration_order():
    registry = RuleRegistry((SalesCoverageTarget(), IncomingStockGate()))
    result = replenish(Dataset((row("A", in_order=2),), {"SKU-1": 10}), registry)
    assert result["audit"][0]["target_stock"] is None


def test_duplicate_rule_id_rejected():
    with pytest.raises(ValueError, match="duplicate"):
        RuleRegistry((SalesCoverageTarget(), SalesCoverageTarget()))


def test_main_push_then_selling_floor_then_sales_priority():
    rows = (row("MAIN", main_push=True), row("HIGH", sales_7d=5), row("LOW", sales_7d=1))
    result = replenish(Dataset(rows, {"SKU-1": 9}))
    assert allocated(result) == {("SKU-1", "MAIN"): 4, ("SKU-1", "HIGH"): 2, ("SKU-1", "LOW"): 1}
    assert result["stock_ledger"][0] == {
        "sku": "SKU-1", "warehouse_stock": 9, "reserved": 2, "allocated": 7, "unused": 0,
    }


def test_avoidance_releases_stock_and_reallocates_to_another_store():
    rows = (row("A", main_push=True), row("B", sales_7d=5), row("C", sales_7d=1))
    result = replenish(Dataset(rows, {"SKU-1": 10}, avoidance=(("A", "B"),)))
    assert allocated(result) == {("SKU-1", "A"): 4, ("SKU-1", "C"): 4}
    assert result["allocation_passes"] == 2
    blocked = next(item for item in result["audit"] if item["store"] == "B")
    assert blocked["eligible"] is False
    assert blocked["trace"][-1]["rule_id"] == "A002"


def test_avoidance_considers_sibling_skus_of_the_same_style():
    rows = (row("A", stock=1), row("B", sku="SKU-2", sales_7d=10), row("C", sku="SKU-2"))
    result = replenish(Dataset(rows, {"SKU-2": 6}, avoidance=(("A", "B"),)))
    assert allocated(result) == {("SKU-2", "C"): 4}


def test_preexisting_conflict_blocks_new_stock_without_deleting_existing_stock():
    rows = (row("A", stock=1), row("B", stock=1), row("C"))
    result = replenish(Dataset(rows, {"SKU-1": 10}, avoidance=(("A", "B"),)))
    assert allocated(result) == {("SKU-1", "C"): 4}
    assert rows[0].stock == rows[1].stock == 1


def test_reserve_is_sku_level_even_on_blocked_rows():
    result = replenish(Dataset((row("A"), row("B", compatible=False)), {"SKU-1": 8}))
    assert {item["warehouse_reserved_qty"] for item in result["audit"]} == {2}
    assert result["audit"][1]["target_stock"] is None


def test_explicit_zero_policy_is_not_replaced_by_defaults():
    result = replenish(Dataset((row("A"),), {"SKU-1": 4}, policy=Policy(warehouse_reserve=0)))
    assert allocated(result) == {("SKU-1", "A"): 4}


def test_no_sales_and_no_main_push_means_no_target():
    result = replenish(Dataset((row("A", sales_30d=0, sales_90d=0),), {"SKU-1": 20}))
    assert result["audit"][0]["target_stock"] == 0
    assert not result["allocations"]


def test_zero_inventory_keeps_valid_audit():
    result = replenish(Dataset((row("A"),), {}))
    assert result["audit"][0]["requested_qty"] == 4
    assert result["stock_ledger"][0]["allocated"] == 0


def test_seeded_random_conservation_order_independence_and_exclusion():
    randomizer = random.Random(481)
    for _ in range(150):
        rows = tuple(row(store, sales_7d=randomizer.randrange(8), sales_30d=randomizer.randrange(16),
                         main_push=bool(randomizer.randrange(2))) for store in ("A", "B", "C", "D"))
        quantity = randomizer.randrange(30)
        policy = Policy(warehouse_reserve=randomizer.randrange(5))
        data = Dataset(rows, {"SKU-1": quantity}, policy, (("A", "B"), ("B", "C")))
        result = replenish(data)
        shuffled = list(rows)
        randomizer.shuffle(shuffled)
        assert result == replenish(replace(data, rows=tuple(shuffled)))
        ledger = result["stock_ledger"][0]
        assert quantity == ledger["reserved"] + ledger["allocated"] + ledger["unused"]
        stores = {item["store"] for item in result["allocations"]}
        assert not {"A", "B"} <= stores and not {"B", "C"} <= stores
        for item in result["audit"]:
            assert item["allocated_qty"] <= (item["requested_qty"] or 0)
        assert result["allocation_passes"] <= len(rows) + 1
