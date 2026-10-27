"""Credential refusal without persisting credential values."""

import os


class CredentialLeak(ValueError):
    """A credential reached a persistence boundary."""


class Guard:
    def __init__(self, env_names: list[str]):
        self._env_names = tuple(env_names)

    def check(self, data: bytes) -> bytes:
        for name in self._env_names:
            needle = os.environ.get(name, "").encode()
            if needle and needle in data:
                raise CredentialLeak("credential reached a ledger write")
        return data
