"""Empty-context floor, with evidence-carrying selections refused."""

from bicentennial.api.adapters.nomemory import NoMemory
from bicentennial.contracts.items import reader_view

from .common import run_arm


def run(inp, *, score):
    arm = run_arm(inp, NoMemory, score=score)
    options = {i["item_id"]: reader_view(i)["options"]
               for i in sorted(inp.pack["items"], key=lambda i: i["item_id"])}
    for report in arm["reports"]:
        selected = report["selected_option"]
        if report["in_context"] is True or any(
                o["option_id"] == selected and o["tokens"] for o in options[report["item_id"]]):
            raise ValueError("no-memory context carries evidence")
    return arm
