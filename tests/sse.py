"""Reading a server-sent event stream's body in tests."""
import json


def parse_events(body: str) -> list[dict[str, str]]:
    """Each event block that carries data, as its fields (id, event, data); comments (keepalives) are skipped."""
    events: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in body.splitlines():
        if line.startswith(":"):
            continue
        if not line:
            if "data" in current:
                events.append(current)
            current = {}
            continue
        key, _, value = line.partition(": ")
        current[key] = value
    return events


def data_events(body: str) -> list[tuple[int, dict]]:
    """(id, decoded data) for each event, in order."""
    return [(int(e["id"]), json.loads(e["data"])) for e in parse_events(body)]
