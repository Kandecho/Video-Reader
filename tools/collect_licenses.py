"""Record installed wheel licenses without changing installed distributions."""
from importlib import metadata
import json
from pathlib import Path
import shutil

root = Path(__file__).resolve().parents[1]
destination = root / "licenses" / "python-packages"
destination.mkdir(parents=True, exist_ok=True)
inventory = []
for dist in sorted(metadata.distributions(), key=lambda d: d.metadata.get("Name", "").lower()):
    name = dist.metadata.get("Name", "unknown")
    license_files = []
    for relative in dist.files or []:
        lowered = str(relative).lower().replace("\\", "/")
        if any(part in lowered for part in ("/licenses/", "/license", "/copying", "/notice")):
            source = Path(dist.locate_file(relative)).resolve()
            if source.is_file():
                # Keep only paths inside the wheel; no RECORD traversal outside site-packages.
                parts = [p for p in Path(str(relative)).parts if p not in ("..", ".")]
                target = destination / name / Path(*parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
                license_files.append(str(target.relative_to(root)).replace("\\", "/"))
    inventory.append({"name": name, "version": dist.version,
                      "license_expression": dist.metadata.get("License-Expression"),
                      "license_metadata": dist.metadata.get("License"),
                      "classifiers": [c for c in dist.metadata.get_all("Classifier", []) if c.startswith("License")],
                      "retained_license_files": license_files})
(root / "licenses" / "python-packages.json").write_text(json.dumps(inventory, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({"distributions": len(inventory), "license_files": sum(len(d["retained_license_files"]) for d in inventory)}))
