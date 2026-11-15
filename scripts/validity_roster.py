"""Draw the validity round's seeds and place its lives from the draw (validity-1 declaration §2).

Rounds 1 and 2 follow results/validity-1/DECLARATION.md §2 and results/validity-2/DECLARATION.md §2,
respectively.

`draw` writes ten design seeds and sixteen ordered spares and prints only the file's sha256 (the
commitment) and the counts. `place` freezes the validation spec from that draw, or writes a void
receipt when the dry run stops.

With `--packs 3 --beacon`, draw derives thirty design seeds and forty-eight ordered spares from
an already published beacon round and the blobs of the run commit (HEAD), read from Git's objects with
no inherited GIT_ variable and no replace refs; verify recomputes its bytes.
`--rehearsal` uses fixed public integers. Place maps positions 1–10 to A, 11–20 to B and 21–30 to C. Within
pack X, odd positions name t2-g1-1 through t2-g1-5 and even positions t2-g2-1 through t2-g2-5;
each pack walks the public T2 row order. Packs share one ordered spare list, excluding every
replacement attempted earlier, including failures. A stop in any pack voids the whole draw,
writing only a receipt and no specs. No command prints a seed.
"""

import argparse
import hashlib
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
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


def collisions(seeds, root=ROOT, *, contents=None):
    """Whole-number matches in supplied byte strings, or regular files outside .git for legacy draws."""
    number = re.compile(rb"(?<![0-9])(" + b"|".join(str(n).encode() for n in seeds) + rb")(?![0-9])")
    found = set()
    if contents is None:
        files = []
        for folder, dirs, names in os.walk(root):
            dirs[:] = [d for d in dirs if d != ".git"]
            for name in names:
                path = Path(folder) / name
                if name != ".git" and stat.S_ISREG(path.lstat().st_mode):
                    files.append(path)
        contents = (Path(path).read_bytes() for path in files)
    for data in contents:
        found.update(int(n) for n in number.findall(data))
    return found


def _read_beacon(path):
    if path is None:
        raise Refused("--beacon is required")
    try:
        data = json.loads(Path(path).read_bytes().decode("utf-8"))
        if not isinstance(data, dict) or set(data) != {"round", "randomness", "signature"}:
            raise ValueError
        if type(data["round"]) is not int or data["round"] <= 0:
            raise ValueError
        if not isinstance(data["randomness"], str) or not re.fullmatch(r"[0-9a-f]{64}", data["randomness"]):
            raise ValueError
        if not isinstance(data["signature"], str) or not re.fullmatch(r"[0-9a-f]+", data["signature"]):
            raise ValueError
        if hashlib.sha256(bytes.fromhex(data["signature"])).hexdigest() != data["randomness"]:
            raise ValueError
    except (OSError, ValueError, RecursionError):
        raise Refused("malformed beacon") from None
    return data


def _candidates(randomness):
    k = 0
    while True:
        yield int.from_bytes(hashlib.sha256(randomness + k.to_bytes(8, "big")).digest()[:8], "big") >> 1
        k += 1


def _git(root, *args, stdin=None):
    """Git on root alone: no inherited GIT_ variable and no replace ref can redirect what it reads."""
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    return subprocess.run(["git", "--no-replace-objects", "-C", str(root), *args],
                          input=stdin, env=env, capture_output=True)


def _commit_blobs(root):
    """Each blob of HEAD's tree, read from the object store; submodule entries are left out."""
    listing = _git(root, "ls-tree", "-r", "-z", "--full-tree", "HEAD")
    listing.check_returncode()
    oids = []
    if listing.stdout and not listing.stdout.endswith(b"\0"):
        raise Refused("invalid commit blob reply")
    for entry in listing.stdout.split(b"\0")[:-1]:
        match = re.fullmatch(rb"([0-7]{6}) ([a-z]+) ([0-9a-f]{40}(?:[0-9a-f]{24})?)\t[^\0]+", entry)
        if match is None:
            raise Refused("invalid commit blob reply")
        mode, kind, oid = match.groups()
        if kind == b"blob":  # regular files, executables and symbolic links; mode 160000 is a commit
            oids.append(oid)
        elif kind != b"commit" or mode != b"160000":
            raise Refused("invalid commit blob reply")
    batch = _git(root, "cat-file", "--batch", stdin=b"".join(oid + b"\n" for oid in oids))
    batch.check_returncode()
    blobs, at = [], 0
    for oid in oids:
        try:
            header = batch.stdout.index(b"\n", at)
            match = re.fullmatch(re.escape(oid) + rb" blob ([0-9]+)", batch.stdout[at:header])
            if match is None:
                raise ValueError
            size = int(match[1])
        except ValueError:
            raise Refused("invalid commit blob reply") from None
        end = header + 1 + size
        if batch.stdout[end:end + 1] != b"\n":
            raise Refused("invalid commit blob reply")
        blobs.append(batch.stdout[header + 1:end])
        at = end + 1
    if at != len(batch.stdout):
        raise Refused("invalid commit blob reply")
    return blobs


def _beacon_draw(beacon, root):
    data = _read_beacon(beacon)
    top = _git(root, "rev-parse", "--show-toplevel")
    if top.returncode != 0 or top.stdout != os.fsencode(Path(root).resolve()) + b"\n":
        raise Refused("root is not the repository top level")
    clean = _git(root, "diff", "--no-ext-diff", "--quiet", "HEAD", "--")
    if clean.returncode != 0:  # guards only that this tool's own code is the commit's
        raise Refused("checkout differs from HEAD")
    blobs = _commit_blobs(root)
    candidates = _candidates(bytes.fromhex(data["randomness"]))
    seeds, seen = [], set()
    while len(seeds) < 78:
        batch = [next(candidates) for _ in range(78 - len(seeds))]
        blocked = collisions(batch, root, contents=blobs)
        for seed in batch:
            if seed in blocked or seed in seen:
                continue
            seeds.append(seed)
            seen.add(seed)
    drawn_at = datetime.fromtimestamp(1692803367 + (data["round"] - 1) * 3, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return canon(dict(design=seeds[:30], spares=seeds[30:], drawn_at=drawn_at)) + b"\n", data["round"]


def verify(draw_path, beacon, *, root=ROOT):
    expected, _ = _beacon_draw(beacon, root)
    if Path(draw_path).read_bytes() != expected:
        print("mismatch")
        return 1
    print(f"verified sha256 {hashlib.sha256(expected).hexdigest()}")
    return 0


def _write_new(path, data):
    out = Path(path).open("xb")  # never overwrite; a failed write removes only the file this call created
    try:
        with out:
            out.write(data)
    except BaseException:
        Path(path).unlink(missing_ok=True)
        raise
    return hashlib.sha256(data).hexdigest()


def draw(out, *, root=ROOT, packs=None, rehearsal=False, beacon=None):
    if beacon is not None and (packs != 3 or rehearsal):
        raise Refused("--beacon requires a real three-pack draw")
    if rehearsal and packs != 3:
        raise Refused("--rehearsal requires --packs 3")
    if Path(out).exists():
        raise Refused("draw output exists" if packs == 3 else f"{out} exists")
    if packs == 3 and not Path(out).parent.is_dir():
        raise Refused("draw output parent is not a directory")
    if packs == 3 and not rehearsal:
        raw, round_ = _beacon_draw(beacon, root)
        digest = _write_new(out, raw)
        print(f"sha256 {digest}")
        print("design 30 spares 48")
        print(f"round {round_}")
        return 0
    design_count, spare_count = (30, 48) if packs == 3 else (DESIGN, SPARES)
    seeds = list(range(2001, 2079)) if rehearsal else [
        secrets.randbits(BITS) for _ in range(design_count + spare_count)]
    if len(set(seeds)) != len(seeds):
        raise Refused("duplicate seed within the draw")
    if not rehearsal and collisions(seeds, root):
        raise Refused("a drawn seed appears as a number in the repository")
    drawn_at = "rehearsal: public integers" if rehearsal else datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    digest = _write_new(out, canon(dict(
        design=seeds[:design_count], spares=seeds[design_count:], drawn_at=drawn_at)) + b"\n")
    print(f"sha256 {digest}")
    print(f"design {design_count} spares {spare_count}")
    if rehearsal:
        print("rehearsal draw: public integers")
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


def _read_draw(path, design_count=DESIGN, spare_count=SPARES):
    raw = Path(path).read_bytes()
    try:
        data = json.loads(raw.decode("utf-8") if design_count == 30 else raw)
    except (ValueError, RecursionError):  # not UTF-8, not JSON, or nested too deep to parse
        raise Refused("malformed draw") from None
    if not isinstance(data, dict) or set(data) != {"design", "spares", "drawn_at"}:
        raise Refused("malformed draw")
    design, spares = data["design"], data["spares"]
    if (type(design) is not list or type(spares) is not list or len(design) != design_count or len(spares) != spare_count
            or any(type(n) is not int or not 0 <= n < 2 ** BITS for n in (*design, *spares))
            or len({*design, *spares}) != design_count + spare_count):  # elements are ints before any set is built
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


def _place_three(rows, design, pool, work, templates):
    """Place in pack order with a fresh list of remaining spares for each call."""
    packs, used = {}, set()
    for index, label in enumerate("ABC"):
        chunk = design[index * 10:(index + 1) * 10]
        seeds = {f"t2-g{genre}-{i}": chunk[2 * (i - 1) + genre - 1]
                 for genre in (1, 2) for i in range(1, 6)}
        lives = [dict(row, seed=seeds[row["life"]]) for row in rows]
        try:
            spec, table = targeted.t2_dry_run(
                targeted._tier_source("T2", lives=lives), templates,
                root=Path(work) / label, pool=[n for n in pool if n not in used])
        except targeted.PlacementError as error:
            if not hasattr(error, "table"):
                raise
            packs[label] = dict(table=error.table, replacements=error.replacements)
            error.pack, error.packs = label, packs
            raise
        packs[label] = dict(spec=spec, table=table, replacements=spec["replacements"])
        used.update(record["replacement_seed"] for record in spec["replacements"])
    return packs


def place_packs(draw_path, work, out_dir, *, templates=None, root=ROOT):
    out = Path(out_dir)
    if out.exists():
        raise Refused("output directory exists")
    if not out.parent.is_dir():
        raise Refused("output parent is not a directory")
    work_root, output_root = Path(work).resolve(), out.resolve()
    if work_root.is_relative_to(output_root) or output_root in {work_root / label for label in "ABC"}:
        raise Refused("work and output directories overlap")
    data, draw_sha = _read_draw(draw_path, 30, 48)
    try:
        rows = targeted.load_tier(root / "tiers/life_specs/t2.toml")["lives"]
    except targeted.PlacementError:
        raise Refused("public T2 roster is malformed") from None
    expected = {(f"t2-g{genre}-{i}", f"G{genre}") for genre in (1, 2) for i in range(1, 6)}
    if len(rows) != 10 or {(row["life"], row["genre"]) for row in rows} != expected:
        raise Refused("public T2 roster is not the named five G1 and five G2 lives")
    if templates is None:
        from bicentennial.items.editions import EDITIONS

        templates = EDITIONS[3]
    receipt = None
    try:
        packs = _place_three(rows, data["design"], data["spares"], work, templates)
    except targeted.PlacementError as error:
        if not hasattr(error, "packs"):
            raise
        packs = error.packs
        receipt = dict(void=True, rule=error.rule, pack=error.pack, draw_sha256=draw_sha,
                       packs={label: dict(table=p["table"], replacements=p["replacements"])
                              for label, p in packs.items()})
    out.mkdir()  # exclusive reservation; cleanup below owns only this directory
    lines = []
    try:
        if receipt is not None:
            digest = _write_new(out / "void.json", canon(receipt) + b"\n")
            lines = [f"void {receipt['rule']} pack {receipt['pack']}", f"draw_sha256 {draw_sha}",
                     f"receipt_sha256 {digest}"]
            lines.extend(f"pack {label} table_rows {len(p['table'])} replacements {len(p['replacements'])}"
                         for label, p in packs.items())
        else:
            lines = [f"draw_sha256 {draw_sha}"]
            for index, (label, p) in enumerate(packs.items()):
                spec = p["spec"]
                text = toml_text(spec, f"Fresh-seed follow-up pack {label} "
                                 f"(positions {index * 10 + 1}-{index * 10 + 10}), "
                                 f"placed from draw sha256 {draw_sha}.")
                if tomllib.loads(text) != spec:
                    raise ValueError("spec TOML does not round-trip")
                spec_out = out / f"pack-{label}.toml"
                spec_sha = _write_new(spec_out, text.encode("utf-8"))
                if targeted.load_tier(spec_out) != spec:
                    raise ValueError("spec TOML fails load_tier")
                table_sha = _write_new(out / f"placement-{label}.json", canon(p["table"]) + b"\n")
                lines.append(f"pack {label} spec_sha256 {spec_sha} table_sha256 {table_sha} "
                             f"lives {len(spec['lives'])} replacements {len(p['replacements'])} "
                             f"table_rows {len(p['table'])}")
            lines.append(f"spares_used {sum(len(p['replacements']) for p in packs.values())} of 48")
    except BaseException:
        shutil.rmtree(out)
        raise
    print("\n".join(lines))
    return 1 if receipt is not None else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    drawing = sub.add_parser("draw")
    drawing.add_argument("--out", required=True, type=Path)
    drawing.add_argument("--packs", type=int, choices=(3,), help="draw for three T2-shaped packs")
    drawing.add_argument("--rehearsal", action="store_true", help="use fixed public integers with --packs 3")
    drawing.add_argument("--beacon", type=Path, help="public beacon JSON for a real three-pack draw")
    verifying = sub.add_parser("verify")
    verifying.add_argument("--packs", type=int, choices=(3,), required=True)
    verifying.add_argument("--beacon", type=Path, help="public beacon JSON to recompute the draw")
    verifying.add_argument("--draw", required=True, type=Path)
    placing = sub.add_parser("place")
    placing.add_argument("--round", type=int, choices=(1, 2))
    placing.add_argument("--draw", required=True, type=Path)
    placing.add_argument("--work", required=True, type=Path)
    placing.add_argument("--spec-out", type=Path)
    placing.add_argument("--table-out", type=Path)
    placing.add_argument("--packs", type=int, choices=(3,), help="place one draw as packs A, B and C")
    placing.add_argument("--out-dir", type=Path, help="new directory for the three specs and tables, or a void receipt")
    args = parser.parse_args(argv)
    if args.command == "place" and args.packs is None:
        if args.out_dir is not None or args.spec_out is None or args.table_out is None:
            parser.error("single-pack place requires --spec-out and --table-out and does not accept --out-dir")
    try:
        if args.command == "verify":
            return verify(args.draw, args.beacon, root=ROOT)
        if args.command == "draw":
            return draw(args.out, packs=args.packs, rehearsal=args.rehearsal, beacon=args.beacon, root=ROOT)
        if args.packs == 3:
            if args.round is not None or args.spec_out is not None or args.table_out is not None:
                raise Refused("--packs cannot be combined with --round, --spec-out or --table-out")
            if args.out_dir is None:
                raise Refused("--packs requires --out-dir")
            return place_packs(args.draw, args.work, args.out_dir)
        return place(args.draw, args.work, args.spec_out, args.table_out, round_=args.round or 1)
    except (Refused, FileExistsError) as error:
        message = str(error) if args.packs is None or isinstance(error, Refused) else "output exists"
        print(f"refused: {message}", file=sys.stderr)
        return 2
    except Exception:
        if args.packs != 3:
            raise
        print("refused: three-pack operation failed", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
