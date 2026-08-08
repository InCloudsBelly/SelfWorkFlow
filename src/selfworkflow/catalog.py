"""Deterministic compilation for the checked-in SelfWorkFlow catalog."""

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PureWindowsPath
import re
import subprocess
import unicodedata

import yaml
from jsonschema import Draft202012Validator


_IDENTIFIER = re.compile(r"[a-z0-9][a-z0-9._-]{0,127}")
MAX_YAML_DEPTH = 64
MAX_YAML_NODES = 1024
MAX_DOCUMENT_BYTES = 1024 * 1024
MAX_SOURCE_BYTES = 8 * 1024 * 1024
FILE_ATTRIBUTE_REPARSE_POINT = 0x400
_WINDOWS_RESERVED_NAMES = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
}
_ERROR_ORDER = {
    code: index
    for index, code in enumerate(
        (
            "duplicate-domain",
            "duplicate-stable-id",
            "duplicate-module-id",
            "content-identity-conflict",
            "alias-invalid",
            "alias-collision",
            "alias-target-unknown",
            "dangling-dependency",
            "dangling-conflict",
            "self-conflict",
            "dependency-cycle",
            "mandatory-conflict",
            "unknown-capability",
            "module-source-unknown",
            "dangling-module-slot",
            "module-invocation-invalid",
            "protected-rule-override",
            "protected-rule-operation-invalid",
            "source-invalid",
            "source-hash-mismatch",
            "source-revision-invalid",
            "source-revision-mismatch",
            "planned-source-must-be-unverified",
            "standard-capability-mismatch",
            "lifecycle-invalid",
            "protected-rules-invalid",
            "duplicate-key",
            "resource-limit",
            "path-invalid",
            "path-reparse",
            "catalog-structure-invalid",
            "catalog-schema-invalid",
            "catalog-input-invalid",
        )
    )
}


class _DuplicateKeyError(ValueError):
    pass


class _YamlResourceError(yaml.YAMLError):
    pass


class _StrictLoader(yaml.SafeLoader):
    max_nodes = MAX_YAML_NODES

    def __init__(self, stream: str) -> None:
        super().__init__(stream)
        self._compose_depth = 0
        self._compose_nodes = 0

    def compose_node(self, parent: yaml.Node | None, index: object) -> yaml.Node:
        if self.check_event(yaml.events.AliasEvent):
            raise _YamlResourceError
        self._compose_nodes += 1
        if self._compose_nodes > self.max_nodes:
            raise _YamlResourceError
        self._compose_depth += 1
        try:
            if self._compose_depth > MAX_YAML_DEPTH:
                raise _YamlResourceError
            return super().compose_node(parent, index)
        except RecursionError:
            raise _YamlResourceError from None
        finally:
            self._compose_depth -= 1


def _construct_unique_mapping(
    loader: _StrictLoader,
    node: yaml.MappingNode,
    deep: bool = False,
) -> dict[object, object]:
    loader.flatten_mapping(node)
    result: dict[object, object] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise _DuplicateKeyError
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_StrictLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


class _ModuleLoader(_StrictLoader):
    max_nodes = 4096


_ModuleLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def _load_yaml(text: str) -> object:
    try:
        return yaml.load(text, Loader=_StrictLoader)
    except _DuplicateKeyError:
        raise CatalogError(("duplicate-key",)) from None
    except _YamlResourceError:
        raise CatalogError(("resource-limit",)) from None


def _load_module_yaml(text: str) -> object:
    try:
        return yaml.load(text, Loader=_ModuleLoader)
    except (_DuplicateKeyError, _YamlResourceError):
        raise CatalogError(("resource-limit",)) from None


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKeyError
        result[key] = value
    return result


def _load_schema_json(text: str) -> dict[str, object]:
    try:
        return json.loads(text, object_pairs_hook=_unique_json_object)
    except _DuplicateKeyError:
        raise CatalogError(("duplicate-key",)) from None


def _validate_schema(schema: object, error_code: str) -> None:
    try:
        Draft202012Validator.check_schema(schema)
    except Exception:
        raise CatalogError((error_code,)) from None
    pending = [(schema, 0)]
    nodes = 0
    while pending:
        value, depth = pending.pop()
        nodes += 1
        if nodes > 50_000 or depth > 64:
            raise CatalogError(("resource-limit",)) from None
        if isinstance(value, dict):
            reference = value.get("$ref")
            if reference is not None and (
                type(reference) is not str
                or not reference.startswith("#/$defs/")
            ):
                raise CatalogError((error_code,)) from None
            pending.extend((item, depth + 1) for item in value.values())
        elif isinstance(value, list):
            pending.extend((item, depth + 1) for item in value)


def _read_document_text(path: Path) -> str:
    metadata = path.lstat()
    if path.is_symlink() or (
        getattr(metadata, "st_file_attributes", 0) & FILE_ATTRIBUTE_REPARSE_POINT
    ):
        raise CatalogError(("path-reparse",)) from None
    if path.stat().st_size > MAX_DOCUMENT_BYTES:
        raise CatalogError(("resource-limit",)) from None
    return path.read_text(encoding="utf-8")


def _load_validated_yaml(
    document_path: Path,
    schema_path: Path,
    error_code: str,
) -> object:
    schema = _load_schema_json(_read_document_text(schema_path))
    _validate_schema(schema, error_code)
    document = _load_yaml(_read_document_text(document_path))
    if next(Draft202012Validator(schema).iter_errors(document), None) is not None:
        raise CatalogError((error_code,)) from None
    return document


def _repository_file(repository_root: Path, relative_path: object) -> Path:
    if type(relative_path) is not str or not relative_path or "\\" in relative_path:
        raise CatalogError(("path-invalid",)) from None
    windows_path = PureWindowsPath(relative_path)
    parts = tuple(relative_path.split("/"))
    if (
        windows_path.is_absolute()
        or windows_path.drive
        or any(part in {"", ".", ".."} for part in parts)
        or unicodedata.normalize("NFC", relative_path) != relative_path
        or any(
            len(part.encode("utf-8")) > 255
            or part.endswith((".", " "))
            or any(character in '<>:"|?*' for character in part)
            or any(ord(character) < 32 or ord(character) == 127 for character in part)
            or part.split(".", 1)[0].casefold() in _WINDOWS_RESERVED_NAMES
            for part in parts
        )
    ):
        raise CatalogError(("path-invalid",)) from None
    current = repository_root
    for part in (None, *parts):
        if part is not None:
            current = current / part
        metadata = current.lstat()
        if current.is_symlink() or (
            getattr(metadata, "st_file_attributes", 0)
            & FILE_ATTRIBUTE_REPARSE_POINT
        ):
            raise CatalogError(("path-reparse",)) from None
    resolved_root = repository_root.resolve(strict=True)
    resolved_file = current.resolve(strict=True)
    try:
        resolved_file.relative_to(resolved_root)
    except ValueError:
        raise CatalogError(("path-invalid",)) from None
    if not resolved_file.is_file():
        raise CatalogError(("path-invalid",)) from None
    return resolved_file


def _source_content_hash(path: Path) -> str:
    if path.stat().st_size > MAX_SOURCE_BYTES:
        raise CatalogError(("resource-limit",)) from None
    digest = hashlib.sha256()
    with path.open("rb") as source_file:
        while chunk := source_file.read(64 * 1024):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _git_root(repository_root: Path) -> Path:
    result = subprocess.run(
        ["git", "-C", str(repository_root), "rev-parse", "--show-toplevel"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="strict",
    )
    if result.returncode != 0:
        raise CatalogError(("source-revision-invalid",)) from None
    discovered = Path(result.stdout.strip()).resolve(strict=True)
    expected = repository_root.resolve(strict=True)
    if discovered != expected:
        raise CatalogError(("source-revision-invalid",)) from None
    return discovered


def _revision_content_hash(
    repository_root: Path,
    relative_path: str,
    revision: str,
    verified_commits: set[str],
) -> str:
    commit = revision.removeprefix("git:")
    if commit not in verified_commits:
        commit_result = subprocess.run(
            ["git", "-C", str(repository_root), "cat-file", "-e", f"{commit}^{{commit}}"],
            check=False,
            capture_output=True,
        )
        if commit_result.returncode != 0:
            raise CatalogError(("source-revision-invalid",)) from None
        verified_commits.add(commit)
    content_result = subprocess.run(
        ["git", "-C", str(repository_root), "show", f"{commit}:{relative_path}"],
        check=False,
        capture_output=True,
    )
    if content_result.returncode != 0:
        raise CatalogError(("source-revision-invalid",)) from None
    return "sha256:" + hashlib.sha256(content_result.stdout).hexdigest()


def _valid_rule_operation(value: object) -> bool:
    if type(value) is not dict or set(value) != {"operation", "id", "constraint"}:
        return False
    constraint = value["constraint"]
    if (
        type(value["operation"]) is not str
        or value["operation"] not in {"add-requirement", "advisory"}
        or type(value["id"]) is not str
        or _IDENTIFIER.fullmatch(value["id"]) is None
        or type(constraint) is not dict
        or set(constraint) != {"kind", "target", "mode", "value"}
        or any(type(constraint[field]) is not str for field in constraint)
        or _IDENTIFIER.fullmatch(constraint["target"]) is None
    ):
        return False
    if value["operation"] == "add-requirement":
        return (
            constraint["kind"] == "capability-state"
            and constraint["mode"] == "equals"
            and constraint["value"] == "supported"
        ) or (
            constraint["kind"] == "verification-status"
            and constraint["mode"] == "equals"
            and constraint["value"] == "passed"
        ) or (
            constraint["kind"] == "review-level"
            and constraint["mode"] == "at-least"
            and constraint["value"] in {"L0", "L1", "L2", "L3"}
        )
    return (
        constraint["kind"] == "workflow-action"
        and constraint["target"] in {"review", "verification", "documentation"}
        and constraint["mode"] == "recommend"
        and constraint["value"] in {"perform", "record"}
    )


def _source_validator(schema: dict[str, object], definition: str) -> Draft202012Validator:
    return Draft202012Validator(
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$defs": schema["$defs"],
            "$ref": f"#/$defs/{definition}",
        }
    )


def _schema_error_code(error: object) -> str:
    if error.validator in {"maxItems", "maxLength"}:
        return "resource-limit"
    path = tuple(error.absolute_path)
    if "source" in path:
        return "source-invalid"
    if "aliases" in path:
        return "alias-invalid"
    if "protectedRuleOperations" in path:
        return "protected-rule-operation-invalid"
    return "catalog-structure-invalid"


def _index_schema_error_code(error: object) -> str:
    path = tuple(error.absolute_path)
    if path and path[0] == "domains" and error.validator == "pattern":
        return "path-invalid"
    if path == ("domains",) and error.validator == "uniqueItems":
        return "duplicate-domain"
    if error.validator in {"maxItems", "maxLength"}:
        return "resource-limit"
    return "catalog-structure-invalid"


class CatalogError(ValueError):
    """Stable, redacted catalog compilation failure."""

    def __init__(self, errors: tuple[str, ...]):
        self.errors = tuple(
            sorted(
                set(errors),
                key=lambda code: (_ERROR_ORDER.get(code, len(_ERROR_ORDER)), code),
            )
        )
        super().__init__("catalog-validation-failed")


@dataclass(frozen=True)
class CompiledCatalog:
    """Canonical catalog bytes and the hash of their catalog payload."""

    content: bytes = b""
    catalog_hash: str = ""


def _compile_catalog(source: str | Path) -> CompiledCatalog:

    source_path = Path(source)
    repository_root = source_path.parent
    schema = _load_schema_json(
        _read_document_text(repository_root / "schemas" / "catalog.schema.json")
    )
    _validate_schema(schema, "catalog-schema-invalid")
    index = _load_yaml(_read_document_text(source_path / "index.yaml"))
    if type(index) is dict and "modules" not in index:
        index["modules"] = None
    index_error = next(_source_validator(schema, "index").iter_errors(index), None)
    if index_error is not None:
        raise CatalogError((_index_schema_error_code(index_error),)) from None
    lifecycle = _load_validated_yaml(
        repository_root / "workflow" / "lifecycle.yaml",
        repository_root / "schemas" / "lifecycle.schema.json",
        "lifecycle-invalid",
    )
    lifecycle_capabilities = lifecycle["capabilities"]["standardNames"]
    standard_capabilities = set(lifecycle_capabilities)
    if index["standardCapabilities"] != lifecycle_capabilities:
        raise CatalogError(("standard-capability-mismatch",)) from None
    protected_rules = _load_validated_yaml(
        repository_root / "workflow" / "protected-rules.yaml",
        repository_root / "schemas" / "protected-rules.schema.json",
        "protected-rules-invalid",
    )
    protected_rule_ids = {rule["id"] for rule in protected_rules["rules"]}
    domains: list[str] = []
    entries: list[dict[str, object]] = []
    for relative_path in index["domains"]:
        document = _load_yaml(
            _read_document_text(_repository_file(source_path, relative_path))
        )
        validation_error = next(
            _source_validator(schema, "domain").iter_errors(document),
            None,
        )
        if validation_error is not None:
            raise CatalogError((_schema_error_code(validation_error),)) from None
        domain = document["domain"]
        domains.append(domain)
        entries.extend({"domain": domain, **entry} for entry in document["entries"])
    modules: list[dict[str, object]] = []
    if index["modules"] is not None:
        module_document = _load_module_yaml(
            _read_document_text(_repository_file(source_path, index["modules"]))
        )
        module_error = next(
            _source_validator(schema, "moduleRegistry").iter_errors(module_document),
            None,
        )
        if module_error is not None:
            raise CatalogError((_schema_error_code(module_error),)) from None
        modules = list(module_document["modules"])
    domain_identities = [
        unicodedata.normalize("NFC", domain).casefold() for domain in domains
    ]
    if len(set(domain_identities)) != len(domain_identities):
        raise CatalogError(("duplicate-domain",)) from None
    entry_ids = [entry["id"] for entry in entries]
    errors: set[str] = set()
    if len(set(entry_ids)) != len(entry_ids):
        errors.add("duplicate-stable-id")
    stable_ids = set(entry_ids)
    module_ids = [module["id"] for module in modules]
    if len(module_ids) != len(set(module_ids)):
        errors.add("duplicate-module-id")
    module_id_set = set(module_ids)
    if any(module["sourceEntryId"] not in stable_ids for module in modules):
        errors.add("module-source-unknown")
    if any(
        capability not in standard_capabilities
        for module in modules
        for capability in module["requiredCapabilities"]
    ):
        errors.add("unknown-capability")
    if any(
        dependency not in module_id_set
        for module in modules
        for dependency in module["dependencies"]
    ) or any(
        conflict not in module_id_set
        for module in modules
        for conflict in module["conflicts"]
    ):
        errors.add("dangling-dependency")
    if modules:
        from selfworkflow.pipeline import load_pipeline

        pipeline = load_pipeline(
            repository_root / "workflow" / "pipeline.yaml",
            repository_root / "schemas" / "pipeline.schema.json",
        )
        slot_map = {
            slot["id"]: (stage["id"], set(slot["allowedInvocationKinds"]))
            for stage in pipeline.document["stages"]
            for slot in stage["slots"]
        }
        for module in modules:
            binding = slot_map.get(module["slot"])
            if binding is None or binding[0] != module["stage"]:
                errors.add("dangling-module-slot")
            elif module["invocation"]["kind"] not in binding[1]:
                errors.add("module-invocation-invalid")
    aliases = [alias for entry in entries for alias in entry["aliases"]]
    rule_operations = [
        operation
        for entry in entries
        for operation in entry["protectedRuleOperations"]
    ]
    if any(not _valid_rule_operation(operation) for operation in rule_operations):
        errors.add("protected-rule-operation-invalid")
    if any(operation["id"] in protected_rule_ids for operation in rule_operations):
        errors.add("protected-rule-override")
    if any(
        type(alias) is not dict
        or set(alias) != {"name", "target"}
        or type(alias.get("name")) is not str
        or _IDENTIFIER.fullmatch(alias["name"]) is None
        or type(alias.get("target")) is not str
        or _IDENTIFIER.fullmatch(alias["target"]) is None
        for alias in aliases
    ):
        errors.add("alias-invalid")
    alias_identities = [
        unicodedata.normalize("NFC", alias["name"]).casefold() for alias in aliases
    ]
    stable_identities = {
        unicodedata.normalize("NFC", entry_id).casefold() for entry_id in entry_ids
    }
    if any(
        alias["target"] not in stable_ids
        for alias in aliases
    ):
        errors.add("alias-target-unknown")
    if any(
        dependency not in stable_ids
        for entry in entries
        for dependency in entry["dependencies"]
    ):
        errors.add("dangling-dependency")
    if any(
        conflict not in stable_ids
        for entry in entries
        for conflict in entry["conflicts"]
    ):
        errors.add("dangling-conflict")
    if any(entry["id"] in entry["conflicts"] for entry in entries):
        errors.add("self-conflict")
    if any(
        capability not in standard_capabilities
        for entry in entries
        for capability in entry["requiredCapabilities"]
    ):
        errors.add("unknown-capability")
    if not {"duplicate-stable-id", "dangling-dependency"} & errors:
        pending_dependencies = {
            entry["id"]: set(entry["dependencies"]) for entry in entries
        }
        resolved_dependencies: set[str] = set()
        while pending_dependencies:
            ready = sorted(
                entry_id
                for entry_id, dependencies in pending_dependencies.items()
                if dependencies <= resolved_dependencies
            )
            if not ready:
                errors.add("dependency-cycle")
                break
            for entry_id in ready:
                resolved_dependencies.add(entry_id)
                del pending_dependencies[entry_id]
    entry_by_id = {entry["id"]: entry for entry in entries}
    if any(
        entry["mandatory"]
        and conflict in entry_by_id
        and entry_by_id[conflict]["mandatory"]
        for entry in entries
        for conflict in entry["conflicts"]
    ):
        errors.add("mandatory-conflict")
    if any(
        "contentHash" not in entry["source"] or "revision" not in entry["source"]
        for entry in entries
    ):
        errors.add("source-invalid")
    if any(
        type(entry["source"]["revision"]) is not str
        or re.fullmatch(r"git:[0-9a-f]{40}", entry["source"]["revision"]) is None
        or type(entry["source"]["contentHash"]) is not str
        or re.fullmatch(
            r"sha256:[0-9a-f]{64}", entry["source"]["contentHash"]
        )
        is None
        for entry in entries
    ):
        errors.add("source-invalid")
    revision_candidates: list[dict[str, object]] = []
    for entry in entries:
        current_hash = _source_content_hash(
            _repository_file(repository_root, entry["source"]["path"])
        )
        if current_hash != entry["source"]["contentHash"]:
            errors.add("source-hash-mismatch")
        else:
            revision_candidates.append(entry)
    git_root = _git_root(repository_root)
    verified_commits: set[str] = set()
    for entry in revision_candidates:
        revision_hash = _revision_content_hash(
            git_root,
            entry["source"]["path"],
            entry["source"]["revision"],
            verified_commits,
        )
        if revision_hash != entry["source"]["contentHash"]:
            errors.add("source-revision-mismatch")
    display_sources: dict[str, str] = {}
    for entry in entries:
        identity = unicodedata.normalize("NFC", entry["displayName"]).casefold()
        previous = display_sources.setdefault(
            identity,
            entry["source"]["contentHash"],
        )
        if previous != entry["source"]["contentHash"]:
            errors.add("content-identity-conflict")
    source_hash_by_id = {
        entry["id"]: entry["source"]["contentHash"] for entry in entries
    }
    alias_sources: dict[str, str] = {}
    alias_content_conflict = False
    if "alias-target-unknown" not in errors:
        for alias, identity in zip(aliases, alias_identities, strict=True):
            target_hash = source_hash_by_id[alias["target"]]
            previous = alias_sources.setdefault(identity, target_hash)
            if previous != target_hash:
                errors.add("content-identity-conflict")
                alias_content_conflict = True
    if (
        not alias_content_conflict
        and (
            len(set(alias_identities)) != len(alias_identities)
            or not set(alias_identities).isdisjoint(stable_identities)
            or not set(alias_identities).isdisjoint(display_sources)
        )
    ):
        errors.add("alias-collision")
    if any(
        entry["source"]["kind"] == "planned"
        and entry["supportStatus"] != "unverified"
        for entry in entries
    ):
        errors.add("planned-source-must-be-unverified")
    if errors:
        raise CatalogError(tuple(errors)) from None
    entries.sort(key=lambda entry: entry["id"])
    modules.sort(key=lambda module: module["id"])
    catalog = {
        "domains": sorted(domains),
        "entries": entries,
        "modules": modules,
        "standardCapabilities": index["standardCapabilities"],
    }
    payload = json.dumps(
        catalog,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    catalog_hash = "sha256:" + hashlib.sha256(payload).hexdigest()
    envelope = {
        "schemaVersion": index["schemaVersion"],
        "catalog": catalog,
        "catalogHash": catalog_hash,
    }
    content = (
        json.dumps(
            envelope,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        + b"\n"
    )
    return CompiledCatalog(content=content, catalog_hash=catalog_hash)


def compile_catalog(source: str | Path) -> CompiledCatalog:
    """Compile a catalog directory into a deterministic JSON envelope."""

    try:
        return _compile_catalog(source)
    except CatalogError:
        raise
    except Exception:
        raise CatalogError(("catalog-input-invalid",)) from None
