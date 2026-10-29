"""Owner-run model staging and dedicated Hermes preparation recipe (stdlib only)."""

import argparse
import hashlib
import re
import shlex
import urllib.request
from pathlib import Path

REVISION = "5c38ec7c405ec4b44b94cc5a9bb96e735b38267a"
HERMES_COMMIT = "d923a5eb487a17c0a68801bba9ef0f56c81040a8"
FILES = {
    "model.onnx": ("onnx/model.onnx", "828e1496d7fabb79cfa4dcd84fa38625c0d3d21da474a00f08db0f559940cf35"),
    "tokenizer.json": ("tokenizer.json", "d241a60d5e8f04cc1b2b3e9ef7a4921b27bf526d9f6050ab90f9267a1f9e5c66"),
    "config.json": ("config.json", "094f8e891b932f2000c92cfc663bac4c62069f5d8af5b5278c4306aef3084750"),
    "tokenizer_config.json": ("tokenizer_config.json", "9261e7d79b44c8195c1cada2b453e55b00aeb81e907a6664974b4d7776172ab3"),
}
REPO = Path(__file__).resolve().parents[1]


def stage(cache):
    cache = Path(cache)
    if cache.resolve().is_relative_to(REPO):
        raise ValueError("model cache must be outside the repository")
    if cache.is_symlink() or any(p.is_symlink() for p in cache.rglob("*")):
        raise ValueError("model cache must hold no symlinks")
    target = cache / "bge-small-en-v1.5-onnx"
    target.mkdir(parents=True, exist_ok=True)
    for name, (remote, expected) in FILES.items():
        dest = target / name
        if dest.exists():
            with dest.open("rb") as stream:
                if hashlib.file_digest(stream, "sha256").hexdigest() != expected:
                    raise ValueError(f"hash mismatch: {name}")
            continue
        partial = dest.with_suffix(dest.suffix + ".part")
        try:
            digest = hashlib.sha256()
            url = f"https://huggingface.co/BAAI/bge-small-en-v1.5/resolve/{REVISION}/{remote}"
            with urllib.request.urlopen(url, timeout=120) as response, partial.open("xb") as stream:
                for chunk in iter(lambda: response.read(1 << 20), b""):
                    digest.update(chunk)
                    stream.write(chunk)
            if digest.hexdigest() != expected:
                raise ValueError(f"hash mismatch: {name}")
            partial.replace(dest)
        finally:
            partial.unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("model-cache", "hermes-source", "hermes", "plugin-source", "commit-a"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args(argv)
    if not re.fullmatch("[0-9a-f]{40}", args.commit_a):
        parser.error("commit-a must be the full commit A id")
    stage(args.model_cache)
    # Inline git-location stripping, also for the commands printed for the owner.
    git = "env -u GIT_DIR -u GIT_WORK_TREE -u GIT_INDEX_FILE -u GIT_COMMON_DIR git"
    source, hermes, plugin, repo = map(shlex.quote,
        (args.hermes_source, args.hermes, args.plugin_source, str(REPO)))
    print(f"{git} clone --no-hardlinks {source} {hermes}")
    print(f"{git} -C {hermes} checkout --detach {HERMES_COMMIT}")
    print(f"(cd {hermes} && uv sync --frozen --extra mcp)")
    print(f"uv pip install --python {shlex.quote(str(Path(args.hermes) / '.venv/bin/python'))} "
          f"--require-hashes -r {shlex.quote(str(REPO / 'systems/locks/omega.txt'))}")
    print(f"{git} -C {repo} worktree add --detach {plugin} {args.commit_a}")


if __name__ == "__main__":
    main()
