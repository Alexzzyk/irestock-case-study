from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass

from .domain import Candidate, Dataset, Decision, priority
from .rules import RuleRegistry


@dataclass(frozen=True)
class StockLedger:
    sku: str
    warehouse_stock: int
    reserved: int
    allocated: int
    unused: int

    def validate(self) -> None:
        if min(self.reserved, self.allocated, self.unused) < 0:
            raise AssertionError("negative stock ledger entry")
        if self.warehouse_stock != self.reserved + self.allocated + self.unused:
            raise AssertionError("warehouse conservation violated")


def _allocate_once(candidates: list[Candidate], data: Dataset, excluded: set[tuple[str, str]]) -> None:
    groups: dict[str, list[Candidate]] = defaultdict(list)
    for candidate in candidates:
        candidate.allocated = 0
        if candidate.eligible and candidate.row.key not in excluded and candidate.need:
            groups[candidate.row.sku].append(candidate)
    for sku, group in groups.items():
        remaining = max(0, data.warehouse.get(sku, 0) - data.policy.warehouse_reserve)
        ranked = sorted(group, key=lambda item: priority(item.row))

        def grant(candidate: Candidate, limit: int) -> None:
            nonlocal remaining
            quantity = min(limit, remaining, candidate.need - candidate.allocated)
            candidate.allocated += quantity
            remaining -= quantity

        for candidate in ranked:
            if candidate.row.main_push:
                grant(candidate, candidate.need)
        for candidate in ranked:
            if not candidate.row.main_push and candidate.row.sales_90d:
                grant(candidate, 1)
        for candidate in ranked:
            grant(candidate, candidate.need)


def _conflict_exclusions(candidates: list[Candidate], data: Dataset) -> dict[tuple[str, str], Decision]:
    grouped: dict[tuple[str, str], list[Candidate]] = defaultdict(list)
    for candidate in candidates:
        grouped[candidate.row.style, candidate.row.store].append(candidate)
    decisions: dict[tuple[str, str], Decision] = {}
    styles = sorted({row.style for row in data.rows})
    for left, right in sorted(tuple(sorted(pair)) for pair in data.avoidance):
        for style in styles:
            sides = (grouped.get((style, left), []), grouped.get((style, right), []))
            existing = [sum(item.row.projected_stock for item in side) for side in sides]
            additions = [sum(item.allocated for item in side) for side in sides]
            if not all(existing[index] + additions[index] > 0 for index in (0, 1)):
                continue
            if all(existing):
                losers = (0, 1)
            elif any(existing):
                losers = (1 if existing[0] else 0,)
            else:
                winner = min((0, 1), key=lambda index: min(priority(item.row) for item in sides[index]))
                losers = (1 - winner,)
            for index in losers:
                for candidate in sides[index]:
                    if candidate.allocated:
                        decisions[candidate.row.key] = Decision(
                            "A002", "allocation", "block", "Mutually exclusive stores share a style", {
                                "pair": [left, right], "style": style,
                                "released_qty": candidate.allocated,
                            },
                        )
    return decisions


def replenish(data: Dataset, registry: RuleRegistry | None = None) -> dict:
    registry = registry or RuleRegistry()
    candidates = [Candidate(row) for row in sorted(data.rows, key=lambda row: row.key)]
    for candidate in candidates:
        registry.evaluate(candidate, data.policy)
    excluded: set[tuple[str, str]] = set()
    passes = 0
    # Exclusions only grow: termination is bounded by the number of candidates.
    while True:
        passes += 1
        _allocate_once(candidates, data, excluded)
        conflicts = _conflict_exclusions(candidates, data)
        new_keys = set(conflicts) - excluded
        if not new_keys:
            break
        excluded.update(new_keys)
        for candidate in candidates:
            if candidate.row.key in new_keys:
                candidate.apply(conflicts[candidate.row.key])
        if passes > len(candidates):
            raise AssertionError("avoidance allocation failed to converge")

    skus = sorted(set(data.warehouse) | {row.sku for row in data.rows})
    allocated_by_sku: dict[str, int] = defaultdict(int)
    for candidate in candidates:
        allocated_by_sku[candidate.row.sku] += candidate.allocated
    ledgers: dict[str, StockLedger] = {}
    for sku in skus:
        stock = data.warehouse.get(sku, 0)
        reserved = min(stock, data.policy.warehouse_reserve)
        quantity = allocated_by_sku[sku]
        ledger = StockLedger(sku, stock, reserved, quantity, stock - reserved - quantity)
        ledger.validate()
        ledgers[sku] = ledger
    for candidate in candidates:
        if candidate.allocated:
            if not candidate.eligible or candidate.allocated > candidate.need:
                raise AssertionError("invalid row allocation")
            candidate.apply(Decision("A001", "allocation", "allocate", "Priority allocation", {
                "quantity": candidate.allocated,
            }))
    return {
        "mode": "replenishment", "allocation_passes": passes,
        "allocations": [
            {"sku": item.row.sku, "store": item.row.store, "quantity": item.allocated}
            for item in candidates if item.allocated
        ],
        "stock_ledger": [asdict(ledgers[sku]) for sku in skus],
        "audit": [item.audit(ledgers[item.row.sku].reserved) for item in candidates],
    }
