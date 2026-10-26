"""Checks spikes/s5/candidates.csv and prints the aggregate counts used in REPORT.md.

Usage: python3 spikes/s5/check_candidates.py [path/to/candidates.csv]
Exit 0 when every check passes, 1 otherwise. Standard library only.
"""
import collections
import csv
import pathlib
import sys

COLS = ["system", "repo_url", "licence", "self_hostable", "hermes_plugin", "mcp_server",
        "ingest_query_api", "aml_add_search", "write_tools", "own_model_calls", "local_embeddings",
        "state_paths", "adoption_signal", "adoption_source", "adoption_date", "adapter_needs", "sources"]
MIN_ROWS = 12
ADOPTION_DATE = "2026-10-26"


def first_word(cell):
    return cell.split(":")[0].split(" ")[0].strip(",;()").lower()


def main(path):
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        header, rows = reader.fieldnames, list(reader)
    errors = []
    if header != COLS:
        errors.append(f"header {header} != {COLS}")
    if len(rows) < MIN_ROWS:
        errors.append(f"{len(rows)} rows < {MIN_ROWS}")
    for r in rows:
        name = r.get("system", "?")
        errors += [f"{name}: empty {c}" for c in COLS if not (r.get(c) or "").strip()]
        for col in ("sources", "adoption_source"):
            urls = [u.strip() for u in (r.get(col) or "").split(";") if u.strip()]
            errors += [f"{name}: {col} entry is not an https URL: {u}" for u in urls
                       if not u.startswith("https://")]
        if r.get("adoption_date") != ADOPTION_DATE:
            errors.append(f"{name}: adoption_date {r.get('adoption_date')} != {ADOPTION_DATE}")
    names = [r["system"] for r in rows]
    errors += [f"duplicate system {n}" for n, k in collections.Counter(names).items() if k > 1]

    print(f"rows: {len(rows)}")
    for col in ("hermes_plugin", "mcp_server", "aml_add_search", "local_embeddings"):
        counts = collections.Counter(first_word(r[col]) for r in rows)
        print(f"{col}: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    print("write_tools none: " + str(sum(first_word(r["write_tools"]) == "none" for r in rows)))
    print("rows with an unverified field: "
          + str(sum(any("unverified" in r[c] for c in COLS) for r in rows)))
    for e in errors:
        print("ERROR " + e)
    return 1 if errors else 0


if __name__ == "__main__":
    default = pathlib.Path(__file__).with_name("candidates.csv")
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else default))
