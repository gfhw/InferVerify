"""Robot Framework listener for live progress + structured result collection.

Robot invokes the listener for every suite/test/keyword event. We use the v3
listener API to capture, per test case:

  * name    — the test case name (e.g. "TTFT 达标")
  * status  — PASS / FAIL
  * message — the failure message, which carries the "expected vs actual"
              details produced by the assertion keywords.

The ``on_progress`` callback is optional and lets the operator surface live
execution progress (test started / finished) to a UI or log stream.
"""


class ProgressListener:
    ROBOT_LISTENER_API_VERSION = 3

    def __init__(self, on_progress=None):
        self.on_progress = on_progress
        self.results = []
        self._current = None

    # ------------------------------------------------------------------ suites
    def start_suite(self, data, result):
        pass

    def end_suite(self, data, result):
        pass

    # ------------------------------------------------------------------- tests
    def start_test(self, data, result):
        self._current = {"name": data.name, "status": None, "message": ""}
        if self.on_progress:
            self.on_progress("started", data.name)

    def end_test(self, data, result):
        if self._current is None:
            return
        self._current["status"] = "PASS" if result.passed else "FAIL"
        self._current["message"] = result.message or ""
        self.results.append(self._current)
        if self.on_progress:
            self.on_progress("finished", data.name, self._current["status"])
        self._current = None

    # -------------------------------------------------------------- misc hooks
    def log_message(self, message):
        pass

    def message(self, message):
        pass

    # ------------------------------------------------------------- convenience
    @property
    def passed(self):
        return [r for r in self.results if r["status"] == "PASS"]

    @property
    def failed(self):
        return [r for r in self.results if r["status"] == "FAIL"]
