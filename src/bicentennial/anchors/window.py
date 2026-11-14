"""Newest whole events within the fixed context window, anchor v1."""

from . import Anchor


class RecentWindow(Anchor):
    def select(self, prompt, now):
        return self.bounded(reversed(self.visible(now)))
