"""Local capability generations without loading models or rehashing large weights."""
from importlib import metadata
from pathlib import Path

from .common import digest


def file_identity(path):
    path = Path(path)
    try:
        stat = path.stat()
    except FileNotFoundError:
        return None
    if not path.is_file():
        return None
    # A reviewed inventory alone cannot detect same-path replacement. Bind it to
    # the actual installed files; small config/inventory files also bind content.
    value = [stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_ino]
    if stat.st_size <= 1_000_000 and path.suffix.lower() in ('.json', '.txt', '.cfg', '.yaml', '.yml'):
        value.append(digest(path.read_bytes().hex()))
    return value


def assets_identity(directory):
    if not directory:
        return None
    root = Path(directory)
    if not root.is_dir():
        return None
    files = [(str(path.relative_to(root)), file_identity(path))
             for path in sorted(root.rglob('*')) if path.is_file()]
    return digest(files)


def runtime_identity(name, site_packages=None, *, assets=False):
    """Read distribution metadata, and optionally the backend's installed assets."""
    if site_packages is None:
        try:
            distribution = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            return None
    else:
        normalized = name.replace('-', '_').lower()
        candidates = sorted(Path(site_packages).glob('*.dist-info'))
        path = next((path for path in candidates
                     if path.name.lower().rsplit('-', 1)[0].replace('-', '_') == normalized), None)
        if path is None:
            return None
        distribution = metadata.PathDistribution(path)
    selected = []
    for item in distribution.files or []:
        if item.name in ('METADATA', 'RECORD') or (assets and item.suffix.lower() in ('.onnx', '.py', '.yaml', '.yml', '.json')):
            selected.append((str(item), file_identity(distribution.locate_file(item))))
    return digest([distribution.version, selected])
