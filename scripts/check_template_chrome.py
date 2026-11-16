import re
from pathlib import Path

root = Path(__file__).resolve().parents[1]
template_roots = (
    root / "accounts" / "templates",
    root / "catalog" / "templates",
    root / "core" / "templates",
    root / "orders" / "templates",
    root / "ops" / "templates",
    root / "mk" / "templates",
)
allowed_document = root / "mk" / "templates" / "base.html"
violations = []
for template_root in template_roots:
    for path in template_root.rglob("*.html"):
        if (
            path == allowed_document
            or path.name.startswith("_")
            or "admin" in path.parts
            or "components" in path.parts
        ):
            continue
        source = path.read_text().lower()
        if re.search(r"<html(?:\s|>)|<head(?:\s|>)", source):
            violations.append(path.relative_to(root))
if violations:
    raise SystemExit(
        "templates own document chrome: " + ", ".join(map(str, violations))
    )
print("template chrome check passed")
