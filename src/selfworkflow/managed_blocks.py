"""Strict managed-block replacement that preserves all unmanaged text."""

BEGIN = "<!-- selfworkflow:begin -->"
END = "<!-- selfworkflow:end -->"


class ManagedBlockError(ValueError):
    pass


def render_managed_block(existing: str, body: str) -> str:
    if "\x00" in existing or "\x00" in body:
        raise ManagedBlockError("managed-block-invalid")
    begin_count = existing.count(BEGIN)
    end_count = existing.count(END)
    if begin_count != end_count or begin_count > 1:
        raise ManagedBlockError("managed-block-invalid")
    block = f"{BEGIN}\n{body.rstrip()}\n{END}"
    if begin_count == 0:
        prefix = existing
        if prefix and not prefix.endswith("\n"):
            prefix += "\n"
        if prefix:
            prefix += "\n"
        return prefix + block + "\n"
    start = existing.index(BEGIN)
    finish = existing.index(END, start) + len(END)
    if existing.find(BEGIN, start + len(BEGIN)) != -1:
        raise ManagedBlockError("managed-block-invalid")
    return existing[:start] + block + existing[finish:]
