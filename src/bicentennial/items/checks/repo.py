"""G1 constant, syntax and branch checks with option-group semantics."""

import ast
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from bicentennial.genres.g1_software.codebase_model import PATHS
from bicentennial.genres.g1_software.diffs import TEMPLATE_FILES, read_state
from bicentennial.genres.g1_software.repo import BRANCH, run_git

AST_PATHS = tuple(p for p in TEMPLATE_FILES if p.endswith(".py"))
REPO_KINDS = ("constant", "defines", "hardcodes", "branch")


def _path(path, allowed):
    if path not in allowed:
        raise ValueError(str(path))


def file_constant(root, path, name, value):
    _path(path, PATHS.values())
    try:
        return read_state(root)[path].get(name) == value
    except ValueError:
        return False


def defines(root, path, name):
    _path(path, AST_PATHS)
    try:
        body = ast.parse((Path(root) / path).read_text(encoding="utf-8")).body
    except (OSError, UnicodeError, SyntaxError):
        return False
    for node in body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == name:
            return True
        targets = node.targets if isinstance(node, ast.Assign) else (
            [node.target] if isinstance(node, ast.AnnAssign) else [])
        if any(isinstance(t, ast.Name) and t.id == name for t in targets):
            return True
    return False


def hardcodes(root, path, value):
    _path(path, AST_PATHS)
    try:
        raw = (Path(root) / path).read_bytes()
    except FileNotFoundError:
        return False
    try:
        texts = [c.value for c in ast.walk(ast.parse(raw.decode("utf-8")))
                 if isinstance(c, ast.Constant) and type(c.value) is str]
    except (UnicodeError, SyntaxError):
        texts = [raw.decode("utf-8", "replace")]
    return any(unicodedata.normalize("NFC", value) in unicodedata.normalize("NFC", text)
               for text in texts)


def on_branch(root, *, tz):
    try:
        return run_git(root, ["symbolic-ref", "--short", "HEAD"], tz=tz).decode().removesuffix("\n") == BRANCH
    except RuntimeError as error:
        if str(error).startswith("git symbolic-ref exited"):
            return False
        raise


@dataclass(frozen=True, kw_only=True)
class RepoCheck:
    kind: str
    path: str | None = None
    name: str | None = None
    value: str | None = None

    def __post_init__(self):
        required = {"constant": (True, True, True), "defines": (True, True, False),
                    "hardcodes": (True, False, True), "branch": (False, False, False)}
        if self.kind not in required or tuple(x is not None for x in (
                self.path, self.name, self.value)) != required[self.kind]:
            raise ValueError("checks")
        if self.path is not None:
            _path(self.path, PATHS.values() if self.kind == "constant" else AST_PATHS)


def _predicates(checks, evaluate):
    result = {}
    for name, groups in checks.items():
        if (type(name) is not str or not name or not isinstance(groups, (list, tuple))
                or not groups or any(not isinstance(g, (list, tuple)) or not g
                                     or any(not isinstance(c, RepoCheck) for c in g) for g in groups)):
            raise ValueError("checks")
        result[name] = any(all(group) for group in [[evaluate(c) for c in g] for g in groups])
    return result


def repo_predicates(root, checks, *, tz):
    def evaluate(c):
        if c.kind == "constant":
            return file_constant(root, c.path, c.name, c.value)
        if c.kind == "defines":
            return defines(root, c.path, c.name)
        if c.kind == "hardcodes":
            return hardcodes(root, c.path, c.value)
        return on_branch(root, tz=tz)
    return _predicates(checks, evaluate)


def repo_state_predicates(state, checks):
    def evaluate(c):
        if c.kind != "constant":
            raise ValueError(c.path or "checks")
        return state.get(c.path, {}).get(c.name) == c.value
    return _predicates(checks, evaluate)
