"""Pure state policy for guided KB assessment; no Qt or service dependencies."""


class AssessmentFlowState:
    STEPS = ("collection", "identity", "shortlist")

    def __init__(self):
        self.reset()

    def reset(self):
        self.states = {name: "pending" for name in self.STEPS}
        self.messages = {}
        self._active = set()
        self._stale_on_finish = set()

    @property
    def active_steps(self):
        return tuple(step for step in self.STEPS if step in self._active)

    def invalidate(self, step):
        index = self.STEPS.index(step)
        for name in self.STEPS[index:]:
            if name in self._active:
                self._stale_on_finish.add(name)
            if self.states[name] != "pending": self.states[name] = "stale"
            self.messages.pop(name, None)

    def started(self, step):
        self.invalidate(step)
        self._active.add(step)
        self._stale_on_finish.discard(step)
        self.states[step] = "running"
        self.messages.pop(step, None)

    def completed(self, step, message=""):
        self._active.discard(step)
        if step in self._stale_on_finish:
            self._stale_on_finish.discard(step)
            self.states[step] = "stale"
            self.messages[step] = "Upstream evidence changed during this analysis; rerun this step"
            return
        self.states[step] = "complete"
        self.messages[step] = message

    def failed(self, step, message):
        self._active.discard(step)
        self._stale_on_finish.discard(step)
        self.states[step] = "failed"
        self.messages[step] = message

    def stale(self, step, message=""):
        """Terminal invalidation: the job ended but its result is no longer current."""
        self.invalidate(step)
        self._active.discard(step)
        self._stale_on_finish.discard(step)
        self.states[step] = "stale"
        self.messages[step] = message

    def next_step(self):
        if self._active: return None
        for name in self.STEPS:
            if self.states[name] != "complete": return name
        return None
