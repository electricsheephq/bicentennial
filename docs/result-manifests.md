# Result manifests

A `RESULT-MANIFEST.json` beside each `RESULT.md` describes that page and hashes
its files. The script derives it from the page and folder; do not type the
derived fields by hand. They restate the page and add no scores or claims.
Extra keys, such as a run's identities, are kept but not checked against the page.

The schema is `bicentennial-result-manifest/1`. Its core fields are:
- `page`: always `RESULT.md`; `title`: the page's first heading.
- `claim_class`: the page's `Claim class:` paragraph, up to a blank line or a
  heading line (one to six `#` and then whitespace or the line's end), with
  spaces joined. A wrapped line that starts with an issue number, such as `#537`, stays
  in the claim.
- `does_not_prove`: the first `## What this does not prove` bullet list,
  with wrapped lines (indented) joined; an empty list when that heading is
  absent. The whole section must be that list: other text in it fails.
- `published`: the folder's date prefix; `release`: its parent folder's name.
- `artifacts`: file paths relative to the folder, SHA-256 hashes and byte sizes,
  sorted by UTF-8 path bytes. Includes the page and files in subfolders, but no
  `RESULT-MANIFEST.json` or subfolder holding its own `RESULT.md`, and none of
  the generated files `.gitignore` keeps out of git (`__pycache__`,
  `.pytest_cache` and `.ruff_cache` folders, `.pyc` and `.pyo` files, `.DS_Store`).
  A manifest covers only its own folder: code a page runs from elsewhere, such as
  a round's reading script, is pinned by the commit the page names.
- `backfilled`: true for the ten pages filled in after publication.
Extra keys survive a refresh. The v0.1 kit's own manifests (schema
`bicentennial-v0.1-result/1`) are parsed and indexed only; their files and page
fields are unchecked, and they stay unchanged. Any other schema fails `check`.

To start a new result's manifest, write
`{"backfilled": false, "schema": "bicentennial-result-manifest/1"}`, plus any
extra keys, beside its page, then run `refresh` and `index`. `backfill` is only
for pages published before manifests existed.

Run from the repository root with `PYTHONPATH=src`:
```sh
python3 scripts/result_manifests.py check
python3 scripts/result_manifests.py backfill
python3 scripts/result_manifests.py refresh results/<release>/<dated-folder>
python3 scripts/result_manifests.py index
```
`check` exits 1 with one line per problem, or 0 when clean. `backfill` writes
only missing manifests. `refresh` updates one v1 manifest's derived fields.
Run `index` after either write command; neither updates the index on its own.

Manifests and `results/MANIFEST-INDEX.json` use canonical JSON: sorted keys,
compact UTF-8, no trailing newline. The index lists every manifest path and
hash in byte order. Its `combined_sha256` hashes lines of `hash`, two spaces,
path and newline. Recompute that combined hash from the repository root:
```sh
LC_ALL=C find results -name RESULT-MANIFEST.json -print0 | LC_ALL=C sort -z | xargs -0 sha256sum | sha256sum
```
This checks published bytes, without running or rescoring the benchmark.
