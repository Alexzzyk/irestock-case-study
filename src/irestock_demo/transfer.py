from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict

from .domain import Candidate, Dataset, priority
from .rules import RuleRegistry


def transfer(data: Dataset) -> dict:
    if data.avoidance:
        raise ValueError("this public transfer demo does not support avoidance pairs")
    candidates = [Candidate(row) for row in sorted(data.rows, key=lambda row: row.key)]
    registry = RuleRegistry()
    for candidate in candidates:
        registry.evaluate(candidate, data.policy)
    incoming = {item.row.key: 0 for item in candidates}
    outgoing = dict(incoming)
    surplus = {
        item.row.key: max(0, item.row.stock - item.target) if item.eligible else 0
        for item in candidates
    }
    donors: dict[tuple[str, str], list[Candidate]] = defaultdict(list)
    for item in candidates:
        if surplus[item.row.key]:
            donors[item.row.sku, item.row.store_brand].append(item)
    moves: list[dict] = []
    for target in sorted(candidates, key=lambda item: priority(item.row)):
        if not target.eligible or not target.need:
            continue
        remaining = target.need
        pool = sorted(donors.get((target.row.sku, target.row.store_brand), []), key=lambda item: (
            -surplus[item.row.key], item.row.store,
        ))
        for source in pool:
            if not remaining:
                break
            if source.row.store == target.row.store:
                continue
            quantity = min(remaining, surplus[source.row.key])
            if not quantity:
                continue
            surplus[source.row.key] -= quantity
            outgoing[source.row.key] += quantity
            incoming[target.row.key] += quantity
            remaining -= quantity
            moves.append({
                "sku": target.row.sku, "source": source.row.store, "target": target.row.store,
                "quantity": quantity, "store_brand": target.row.store_brand,
                "rule_id": "T001", "reason": "Same-brand surplus above donor target",
            })
    balances = [{
        "sku": item.row.sku, "store": item.row.store, "before": item.row.stock,
        "out": outgoing[item.row.key], "in": incoming[item.row.key],
        "after": item.row.stock - outgoing[item.row.key] + incoming[item.row.key],
        "retained_target": item.target,
    } for item in candidates]
    delta_by_sku: dict[str, int] = defaultdict(int)
    for balance in balances:
        delta_by_sku[balance["sku"]] += balance["after"] - balance["before"]
    for delta in delta_by_sku.values():
        if delta:
            raise AssertionError("transfer conservation violated")
    if any(row["after"] < 0 for row in balances):
        raise AssertionError("negative store stock")
    audit = [{
        "sku": item.row.sku, "store": item.row.store, "eligible": item.eligible,
        "target_stock": item.target, "requested_qty": item.need,
        "received_qty": incoming[item.row.key],
        "unfilled_qty": max(0, item.need - incoming[item.row.key]) if item.eligible else None,
        "trace": [asdict(decision) for decision in item.trace],
    } for item in candidates]
    return {"mode": "transfer", "moves": moves, "balances": balances, "audit": audit}
