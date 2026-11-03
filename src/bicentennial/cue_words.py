"""Check action requests for memory cues without loading templates or changing packs."""

import argparse
import ast
import json
import re
from dataclasses import dataclass
from pathlib import Path

# Keep the cue vocabulary here; recall requests are outside this check.
CUE_PHRASES = (
    "usual", "as usual", "as always", "established", "our regular", "like last time",
    "the same as before", "the usual", "my usual", "as before", "same as last time",
    "as we discussed", "as agreed", "the regular", "my regular", "your regular", "routine",
)
_PATTERNS = tuple((phrase, re.compile(r"\b" + r"\s+".join(map(re.escape, phrase.split()))
                                     + r"\b", re.IGNORECASE)) for phrase in CUE_PHRASES)
TEMPLATES = Path(__file__).resolve().parent / "items" / "templates"
# The walker finds these calls by name, so any other use of one of these names could hide a request.
_GUARDED = ("Instance", "replace", "__replace__")


@dataclass(frozen=True)
class Request:
    source: Path
    item: str
    parts: tuple[str, ...]


@dataclass(frozen=True)
class Hit:
    source: Path
    item: str
    phrase: str


def template_requests(root=TEMPLATES):
    """Read every module recursively, checking each action Instance's literal text.

    Each formatted field is a gap, including fields with a literal expression. Unsupported action
    prompt expressions, Instance calls with positional or ** arguments, Instance, replace or
    __replace__ named other than to call it or in an annotation (a renamed import, an assignment, an
    argument), and a prompt or decision table set through replace() or __replace__() fail rather than
    silently losing coverage. A name reached dynamically, such as through getattr, is beyond a source
    walk; pack mode reads the prompts as built.
    """
    root = Path(root)
    if not root.is_dir():
        raise ValueError(f"not a template directory: {root}")
    paths = sorted(root.rglob("*.py"))
    if not paths:
        raise ValueError(f"no template modules: {root}")
    requests = []
    for path in paths:
        tree = ast.parse(path.read_bytes(), filename=str(path))
        calls = sorted((node for node in ast.walk(tree) if isinstance(node, ast.Call)),
                       key=lambda node: (node.lineno, node.col_offset))
        allowed = {id(call.func) for call in calls} | _annotation_nodes(tree)
        for node in ast.walk(tree):
            for guarded in _GUARDED:
                renamed = isinstance(node, ast.ImportFrom) and any(
                    alias.name == guarded and alias.asname not in (None, guarded) for alias in node.names)
                named = ((isinstance(node, ast.Name) and node.id == guarded)
                         or (isinstance(node, ast.Attribute) and node.attr == guarded))
                if renamed or (named and id(node) not in allowed):
                    raise ValueError(f"{path}:{node.lineno}: {guarded} is named other than to call it, "
                                     "so a request built through that name cannot be checked")
        for call in calls:
            name = (call.func.id if isinstance(call.func, ast.Name) else
                    call.func.attr if isinstance(call.func, ast.Attribute) else None)
            if name in ("replace", "__replace__") and any(keyword.arg in (None, "prompt", "decision_table_ref")
                                                          for keyword in call.keywords):
                raise ValueError(f"{path}:{call.lineno}: a prompt set through replace() cannot be checked")
            if name != "Instance":
                continue
            if call.args or any(keyword.arg is None for keyword in call.keywords):
                raise ValueError(f"{path}:{call.lineno}: expected an Instance call with keyword arguments only")
            keywords = {keyword.arg: keyword.value for keyword in call.keywords}
            if "decision_table_ref" not in keywords:
                continue
            prompt = keywords.get("prompt")
            if isinstance(prompt, ast.Constant) and isinstance(prompt.value, str):
                parts = (prompt.value,)
            elif isinstance(prompt, ast.JoinedStr):
                parts = tuple(part.value for part in prompt.values if isinstance(part, ast.Constant))
            else:
                raise ValueError(f"{path}:{call.lineno}: expected a constant or f-string prompt")
            requests.append(Request(path, f"{path.stem}:{call.lineno}:{call.col_offset}", parts))
    return tuple(requests)


def _annotation_nodes(tree):
    """The ids of every node inside a type annotation, where naming a guarded name builds nothing."""
    roots = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            arguments = node.args
            roots.append(node.returns)
            roots.extend(arg.annotation for arg in (*arguments.posonlyargs, *arguments.args,
                                                    *arguments.kwonlyargs, arguments.vararg,
                                                    arguments.kwarg) if arg is not None)
        elif isinstance(node, ast.AnnAssign):
            roots.append(node.annotation)
    return {id(inner) for root in roots if root is not None for inner in ast.walk(root)}


def pack_requests(root):
    """Read action prompts in all per-branch item files beneath a pack directory."""
    root = Path(root)
    if not root.is_dir():
        raise ValueError(f"not a pack directory: {root}")
    paths = sorted(root.rglob("items.*.json"))
    if not paths:
        raise ValueError(f"no branch item files: {root}")
    requests = []
    for path in paths:
        items = json.loads(path.read_bytes())
        if not isinstance(items, list):
            raise ValueError(f"{path}: expected an item array")
        for index, item in enumerate(items):
            if not isinstance(item, dict) or not isinstance(item.get("stage"), str):
                raise ValueError(f"{path}: item {index}: expected an item with a stage")
            if item["stage"] != "act":
                continue
            if not all(isinstance(item.get(key), str) for key in ("item_id", "prompt")):
                raise ValueError(f"{path}: item {index}: expected item_id and prompt strings")
            requests.append(Request(path, item["item_id"], (item["prompt"],)))
    return tuple(requests)


def check_requests(requests):
    """Return one hit per matching vocabulary phrase per request, in input order."""
    return tuple(Hit(request.source, request.item, phrase)
                 for request in requests for phrase, pattern in _PATTERNS
                 if any(pattern.search(part) for part in request.parts))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--templates", type=Path, default=TEMPLATES,
                        help="source template directory (checked on every run)")
    parser.add_argument("packs", type=Path, nargs="*", help="optional pack directories")
    args = parser.parse_args(argv)
    try:
        requests = list(template_requests(args.templates))
        for pack in args.packs:
            requests.extend(pack_requests(pack))
        hits = check_requests(requests)
    except (OSError, ValueError, SyntaxError) as error:
        parser.error(str(error))
    for hit in hits:
        print(f"{hit.source}: {hit.item}: {hit.phrase}")
    return int(bool(hits))


if __name__ == "__main__":
    raise SystemExit(main())
