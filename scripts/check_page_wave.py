from pathlib import Path

root = Path(__file__).resolve().parents[1]
pages = root / "docs" / "PAGES.md"
content = pages.read_text()
current_rows = [
    line
    for line in content.splitlines()
    if line.startswith("|") and line.endswith("| Current |")
]
if not current_rows:
    raise SystemExit("no current wave pages are listed")
for line in current_rows:
    columns = [column.strip().strip("`") for column in line.strip("|").split("|")]
    if len(columns) != 4 or not columns[1] or not columns[2].startswith("/"):
        raise SystemExit(f"invalid current page row: {line}")
if "Deferred" not in content or "P2P" not in content:
    raise SystemExit("deferred P2P scope is missing from the page map")
print(f"page wave inventory passed ({len(current_rows)} current pages)")
