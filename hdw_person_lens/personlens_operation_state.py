"""Qt-free ownership of Activity progress for overlapping person operations."""


class PersonOperationState:
    def __init__(self):
        self._next = 0
        self._active = {}

    def begin(self, label: str) -> int:
        self._next += 1
        self._active[self._next] = (label, 0)
        return self._next

    def progress(self, token: int, value: int) -> bool:
        if token not in self._active: return False
        label, _ = self._active[token]
        self._active[token] = (label, max(0, min(100, int(value))))
        return token == next(reversed(self._active))

    def finish(self, token: int) -> bool:
        if token not in self._active: return False
        del self._active[token]
        return True

    def get(self, token: int) -> tuple[str, int] | None:
        return self._active.get(token)

    @property
    def active_operations(self) -> tuple[tuple[int, str, int], ...]:
        """Oldest first; immutable snapshot for presentation without Qt dependencies."""
        return tuple((token, label, progress) for token, (label, progress) in self._active.items())

    @property
    def current_progress(self) -> int:
        return self._active[next(reversed(self._active))][1] if self._active else 0

    @property
    def busy(self) -> bool:
        return bool(self._active)

    @property
    def current_label(self) -> str:
        return self._active[next(reversed(self._active))][0] if self._active else ""

    @property
    def active_count(self) -> int:
        return len(self._active)
