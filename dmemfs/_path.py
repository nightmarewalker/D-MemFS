import posixpath


def normalize_path(path: str) -> str:
    converted = path.replace("\\", "/")
    if not converted:
        return "/"

    # Traversal check: simulate path resolution from root (depth 0)
    # relative paths are treated as if prepended with "/"
    parts = converted.split("/")
    depth = 0
    for part in parts:
        if part == "..":
            depth -= 1
            if depth < 0:
                raise ValueError(f"Path traversal attempt detected: '{path}'")
        elif part and part != ".":
            depth += 1

    # Normalize: make absolute then normpath
    if not converted.startswith("/"):
        converted = "/" + converted
    normalized = posixpath.normpath(converted)
    return normalized
