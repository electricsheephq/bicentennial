"""Draw the validity round's seeds and place its lives from the draw (validity-1 declaration §2).

Rounds 1 and 2 follow results/validity-1/DECLARATION.md §2 and results/validity-2/DECLARATION.md §2,
respectively.

`draw` writes ten design seeds and sixteen ordered spares and prints only the file's sha256 (the
commitment) and the counts. `place` freezes the validation spec from that draw, or writes a void
receipt when the dry run stops. Neither prints a seed.
"""

import argparse
import hashlib
import json
import os
import re
import secrets
import stat
import sys
import tomllib
from datetime import UTC, datetime
from pathlib import Path

from bicentennial.canon import canon
from bicentennial.world import targeted

ROOT = Path(__file__).resolve().parents[1]
DESIGN, SPARES, BITS = 10, 16, 63
BARE_KEY = re.compile(r"[A-Za-z0-9_-]+")


class Refused(ValueError):
    pass


def collisions(seeds, root=ROOT):
    """Seeds whose decimal text appears as a whole number in any regular file under `root` (outside .git)."""
    number = re.compile(rb"(?<![0-9])(" + b"|".join(str(n).encode() for n in seeds) + rb")(?![0-9])")
    found = set()
    for folder, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d != ".git"]
        for name in files:
            path = Path(folder) / name
            if name != ".git" and stat.S_ISREG(path.lstat().st_mode):
                found.update(int(n) for n in number.findall(path.read_bytes()))
    return found


def _write_new(path, data):
    out = Path(path).open("xb")  # never overwrite; a failed write removes only the file this call created
    try:
        with out:
            out.write(data)
    except BaseException:
        Path(path).unlink(missing_ok=True)
        raise
    return hashlib.sha256(data).hexdigest()


def draw(out, *, root=ROOT):
    if Path(out).exists():
        raise Refused(f"{out} exists")
    seeds = [secrets.randbits(BITS) for _ in range(DESIGN + SPARES)]
    if len(set(seeds)) != len(seeds):
        raise Refused("duplicate seed within the draw")
    if collisions(seeds, root):
        raise Refused("a drawn seed appears as a number in the repository")
    drawn_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    digest = _write_new(out, canon(dict(design=seeds[:DESIGN], spares=seeds[DESIGN:], drawn_at=drawn_at)) + b"\n")
    print(f"sha256 {digest}")
    print(f"design {DESIGN} spares {SPARES}")
    return 0


def _key(key):
    return key if BARE_KEY.fullmatch(key) else json.dumps(key)


def _value(value):
    if isinstance(value, dict):
        return "{ " + ", ".join(f"{_key(k)} = {_value(v)}" for k, v in value.items()) + " }"
    if isinstance(value, list):
        return "[" + ", ".join(_value(v) for v in value) + "]"
    if type(value) in (bool, int, str):
        return json.dumps(value, ensure_ascii=False)
    raise TypeError(f"no TOML form for {type(value).__name__}")


def toml_text(spec, comment):
    tables = {k: v for k, v in spec.items() if isinstance(v, dict) or isinstance(v, list) and v
              and all(isinstance(x, dict) for x in v)}
    lines = [f"# {comment}", *(f"{_key(k)} = {_value(v)}" for k, v in spec.items() if k not in tables)]
    for name, value in tables.items():
        for table in [value] if isinstance(value, dict) else value:
            lines += ["", f"[{_key(name)}]" if isinstance(value, dict) else f"[[{_key(name)}]]",
                      *(f"{_key(k)} = {_value(v)}" for k, v in table.items())]
    return "\n".join(lines) + "\n"


def _read_draw(path):
    raw = Path(path).read_bytes()
    try:
        data = json.loads(raw)
    except (ValueError, RecursionError):  # not UTF-8, not JSON, or nested too deep to parse
        raise Refused("malformed draw") from None
    if not isinstance(data, dict) or set(data) != {"design", "spares", "drawn_at"}:
        raise Refused("malformed draw")
    design, spares = data["design"], data["spares"]
    if (type(design) is not list or type(spares) is not list or len(design) != DESIGN or len(spares) != SPARES
            or any(type(n) is not int or not 0 <= n < 2 ** BITS for n in (*design, *spares))
            or len({*design, *spares}) != DESIGN + SPARES):  # elements are ints before any set is built
        raise Refused("malformed draw")
    return data, hashlib.sha256(raw).hexdigest()


def place(draw_path, work, spec_out, table_out, *, round_=1, templates=None, root=ROOT):
    if Path(spec_out).resolve() == Path(table_out).resolve():
        raise Refused("--spec-out and --table-out are the same path")
    for path in (spec_out, table_out):
        if Path(path).exists():
            raise Refused(f"{path} exists")
        if not Path(path).parent.is_dir():
            raise Refused(f"{Path(path).parent} is not a directory")
    data, draw_sha = _read_draw(draw_path)
    if templates is None:  # the edition map lands in a sibling PR; import it only when placing for real
        from bicentennial.items.editions import EDITIONS

        templates = EDITIONS[3 if round_ == 2 else 2]
    rows = targeted.load_tier(root / "tiers/life_specs/t2.toml")["lives"]
    if round_ == 2:
        first = next((row for row in rows if row["genre"] == "G1"), None)
        if first is None:
            raise Refused("public T2 roster has no G1 row")
        rows = [dict(first, life=f"t2-g1-{n}", seed=seed) for n, seed in enumerate(data["design"], 1)]
    else:
        if len(rows) != DESIGN:
            raise Refused("public T2 roster is not ten lives")
        rows = [dict(row, seed=seed) for row, seed in zip(rows, data["design"], strict=True)]
    try:
        spec, table = targeted.t2_dry_run(targeted._tier_source("T2", lives=rows), templates,
                                          root=work, pool=data["spares"])
    except targeted.PlacementError as error:
        if not hasattr(error, "table"):
            raise
        digest = _write_new(table_out, canon(dict(
            void=True, rule=error.rule, draw_sha256=draw_sha, table=error.table,
            replacements=error.replacements)) + b"\n")
        print(f"void {error.rule}")
        print(f"draw_sha256 {draw_sha}")
        print(f"receipt_sha256 {digest}")
        print(f"table_rows {len(error.table)} replacements {len(error.replacements)}")
        return 1
    text = toml_text(spec, f"Validity round {round_} validation spec, placed from draw sha256 {draw_sha}.")
    if tomllib.loads(text) != spec:
        raise ValueError("spec TOML does not round-trip")
    spec_sha = _write_new(spec_out, text.encode("utf-8"))
    try:
        loaded = targeted.load_tier(spec_out)
    except BaseException:
        Path(spec_out).unlink()  # created above by this call
        raise
    if loaded != spec:
        Path(spec_out).unlink()
        raise ValueError("spec TOML fails load_tier")
    try:
        table_sha = _write_new(table_out, canon(table) + b"\n")
    except BaseException:
        Path(spec_out).unlink()  # created above by this call; a failed place leaves neither output
        raise
    print(f"draw_sha256 {draw_sha}")
    print(f"spec_sha256 {spec_sha}")
    print(f"table_sha256 {table_sha}")
    print(f"lives {len(spec['lives'])} replacements {len(spec['replacements'])} table_rows {len(table)}")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    drawing = sub.add_parser("draw")
    drawing.add_argument("--out", required=True, type=Path)
    placing = sub.add_parser("place")
    placing.add_argument("--round", type=int, choices=(1, 2), default=1)
    placing.add_argument("--draw", required=True, type=Path)
    placing.add_argument("--work", required=True, type=Path)
    placing.add_argument("--spec-out", required=True, type=Path)
    placing.add_argument("--table-out", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "draw":
            return draw(args.out)
        return place(args.draw, args.work, args.spec_out, args.table_out, round_=args.round)
    except (Refused, FileExistsError) as error:
        print(f"refused: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
