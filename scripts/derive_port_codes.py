#!/usr/bin/env python3
"""Derive the source-backed port/code table used by the port comparison policy.

A parenthesised five-letter token is only treated as supplementary formatting
when the source registry itself establishes, repeatedly, that it identifies that
port. This script recomputes that evidence so the table in
``backend/intelligence/policies/ports.py`` can be audited and regenerated rather
than hand-tuned.

    python scripts/derive_port_codes.py --source resources/sdoc-hackathon-bundle

Inclusion rule: a (port text, code) pair must occur at least MIN_OBSERVATIONS
times **and** be a strict majority of that port's observations, i.e. more than
half. A port whose evidence is split or thin is deliberately left out, so its
code stays unestablished and a difference is preserved rather than discarded.

**Provenance.** This derives a *corpus convention*: what the documents being
checked repeatedly write. It is learned from development data and is not an
external validation of geographic truth. No live port registry was consulted.
Treating it as supplementary formatting is a team decision — see
``PORT_TABLE_APPROVED`` in ``backend/intelligence/policies/ports.py``.
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import sys
from pathlib import Path

MIN_OBSERVATIONS = 3

_PORT_LINE = re.compile(
    r"^(?:POL|POD|Port of Loading[^:]*|Port of Discharge[^:]*|Load Port|"
    r"Discharge Port|PORT OF \w+)\s*:\s*(.+)$",
    re.IGNORECASE,
)
_CODE = re.compile(r"\(([A-Z]{5})\)")


def observations(root: Path) -> dict:
    counts: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for path in sorted((root / "attachments").glob("*.txt")):
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            match = _PORT_LINE.match(line)
            if not match:
                continue
            value = match.group(1).strip()
            code = _CODE.search(value)
            if not code:
                continue
            place = _CODE.sub("", value).replace("  ", " ").strip().casefold().strip(" ,;.")
            counts[place][code.group(1)] += 1
    return counts


def derive(counts: dict, minimum: int = MIN_OBSERVATIONS) -> tuple[dict, list]:
    """Accept only a strict majority backed by enough observations.

    A code seen 3 times out of 7 leads the field but is not what the port is
    mostly written with, so it is rejected. Both conditions must hold:
    ``top_count >= minimum`` and ``top_count > total / 2``.
    """
    table: dict[str, str] = {}
    rejected: list[dict] = []
    for place, codes in sorted(counts.items()):
        ranked = codes.most_common()
        top_code, top_count = ranked[0]
        runner_up = ranked[1][1] if len(ranked) > 1 else 0
        total = sum(codes.values())
        if top_count < minimum:
            rejected.append({"port": place, "reason": "too few observations",
                             "counts": dict(codes)})
            continue
        if top_count == runner_up:
            rejected.append({"port": place, "reason": "evidence is split",
                             "counts": dict(codes)})
            continue
        if top_count * 2 <= total:
            rejected.append({"port": place, "reason": "not a strict majority",
                             "counts": dict(codes),
                             "top": top_count, "total": total})
            continue
        table[place] = top_code
    return table, rejected


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--min-observations", type=int, default=MIN_OBSERVATIONS)
    parser.add_argument("--emit-python", action="store_true",
                        help="print the table as a Python literal")
    args = parser.parse_args()

    counts = observations(args.source)
    table, rejected = derive(counts, args.min_observations)

    if args.emit_python:
        print("VERIFIED_PORT_CODES = {")
        for place, code in sorted(table.items()):
            total = counts[place][code]
            print(f'    "{place}": "{code}",'.ljust(56) + f"# {total} observations")
        print("}")
        return 0

    print(json.dumps({
        "source": str(args.source),
        "min_observations": args.min_observations,
        "accepted": table,
        "rejected": rejected,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
