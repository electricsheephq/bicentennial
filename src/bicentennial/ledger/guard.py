"""Credential refusal without persisting credential values."""

import os

from bicentennial.canon import canon


class CredentialLeak(ValueError):
    """A credential reached a persistence boundary."""


class Guard:
    def __init__(self, env_names: list[str]):
        self._env_names = tuple(env_names)

    def check(self, data: bytes) -> bytes:
        for name in self._env_names:
            value = os.environ.get(name, "")
            # Both writers persist canon bytes, which escape quotes, backslashes and controls.
            if value and any(n in data for n in (value.encode(), canon(value)[1:-1])):
                raise CredentialLeak("credential reached a ledger write")
        return data
