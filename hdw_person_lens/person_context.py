"""Shared, UI-independent active-person identity for PersonLens navigation."""
from dataclasses import dataclass


@dataclass
class PersonContext:
    name: str = ""

    def select(self, name: str) -> bool:
        """Store only explicit names; return whether the shared selection changed."""
        name = name.strip() if isinstance(name, str) else ""
        changed = self.name != name
        self.name = name
        return changed

    def reconcile(self, existing_names) -> bool:
        """Drop a deleted identity without choosing an unrelated replacement."""
        if self.name and self.name not in existing_names:
            self.name = ""
            return True
        return False
