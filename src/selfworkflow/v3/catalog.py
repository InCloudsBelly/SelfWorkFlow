"""Strict, deterministic compilation for the independent V3 catalog."""

import hashlib
import json
import math
import os
from pathlib import Path, PureWindowsPath
import re
import stat
from typing import Any

import yaml

from selfworkflow.v3.contracts import ContractError, load_contract


_IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_MAX_DOCUMENT_BYTES = 1024 * 1024
_MAX_SOURCE_BYTES = 8 * 1024 * 1024
_REPARSE_POINT = 0x400
_INDEX_FIELDS = {"schemaVersion", "domains", "modules"}
_REF_FIELDS = {"id", "ref", "hash"}
_DOMAIN_FIELDS = {"schemaVersion", "id", "modules"}


class _DuplicateKeyError(ValueError):
    pass


class _AliasError(ValueError):
    pass


class _NonJsonYamlError(ValueError):
    pass


class _StrictLoader(yaml.SafeLoader):
    max_nodes = 4096

    def __init__(self, stream: str) -> None:
        super().__init__(stream)
        self._nodes = 0
        self._depth = 0

    def compose_node(self, parent: yaml.Node | None, index: object) -> yaml.Node:
        if self.check_event(yaml.events.AliasEvent):
            raise _AliasError
        self._nodes += 1
        if self._nodes > self.max_nodes:
            raise ValueError("resource limit")
        self._depth += 1
        try:
            if self._depth > 64:
                raise ValueError("resource limit")
            return super().compose_node(parent, index)
        finally:
            self._depth -= 1


def _construct_unique_mapping(
    loader: _StrictLoader,
    node: yaml.MappingNode,
    deep: bool = False,
) -> dict[object, object]:
    loader.flatten_mapping(node)
    result: dict[object, object] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if type(key) is not str:
            raise _NonJsonYamlError
        if key in result:
            raise _DuplicateKeyError
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_StrictLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


class CatalogError(ValueError):
    """Stable V3 catalog compilation failure."""

    def __init__(self, reason: str = "v3-catalog-invalid") -> None:
        self.reason = reason
        super().__init__(reason)


class CompiledCatalog:
    """Artifact issued only after the V3 catalog compiler succeeds."""

    __slots__ = ("_document", "_content", "_catalog_hash", "__seal")

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("CompiledCatalog is issued by compile_catalog")

    def __setattr__(self, _name: str, _value: object) -> None:
        raise AttributeError("CompiledCatalog is immutable")

    @property
    def document(self) -> dict[str, Any]:
        return self._document

    @property
    def content(self) -> bytes:
        return self._content

    @property
    def catalog_hash(self) -> str:
        return self._catalog_hash

    def _has_valid_seal(self) -> bool:
        return getattr(self, "_CompiledCatalog__seal", None) is _CATALOG_SEAL


_CATALOG_SEAL = object()


def _issue_compiled_catalog(
    document: dict[str, Any], content: bytes, catalog_hash: str,
) -> CompiledCatalog:
    artifact = object.__new__(CompiledCatalog)
    object.__setattr__(artifact, "_document", document)
    object.__setattr__(artifact, "_content", content)
    object.__setattr__(artifact, "_catalog_hash", catalog_hash)
    object.__setattr__(artifact, "_CompiledCatalog__seal", _CATALOG_SEAL)
    return artifact


def compile_catalog(source: object = None) -> CompiledCatalog:
    index = _v3_index_path(source)
    root = index.parents[2]
    catalog_root = root / "catalog" / "v3"
    document = _load_yaml_file(index, _MAX_DOCUMENT_BYTES, root)
    if not isinstance(document, dict):
        raise CatalogError("v3-catalog-root-invalid")
    _require_fields(document, _INDEX_FIELDS, "v3-catalog-unknown-field")
    if document.get("schemaVersion") != 3:
        raise CatalogError("v3-catalog-version-mismatch")
    if not isinstance(document.get("domains"), list) or not isinstance(document.get("modules"), list):
        raise CatalogError("v3-catalog-schema-invalid")

    domain_declarations = _read_refs(document["domains"])
    module_declarations = _read_refs(document["modules"])
    domains: list[dict[str, Any]] = []
    domain_modules: dict[str, list[str]] = {}
    for declaration in domain_declarations:
        target = _safe_ref(catalog_root, declaration["ref"])
        source_bytes = _read_bytes(target, _MAX_SOURCE_BYTES, catalog_root)
        _verify_hash(source_bytes, declaration["hash"])
        domain = _load_yaml_bytes(source_bytes)
        _validate_domain(domain)
        if domain["id"] != declaration["id"]:
            raise CatalogError("v3-catalog-source-id-mismatch")
        domain_modules[domain["id"]] = domain["modules"]
        domains.append({
            "id": declaration["id"],
            "ref": declaration["ref"],
            "hash": declaration["hash"],
        })

    modules: list[dict[str, Any]] = []
    module_ids: set[str] = set()
    for declaration in module_declarations:
        target = _safe_ref(catalog_root, declaration["ref"])
        source_bytes = _read_bytes(target, _MAX_SOURCE_BYTES, catalog_root)
        _verify_hash(source_bytes, declaration["hash"])
        try:
            source_document = _load_yaml_bytes(source_bytes)
            module = load_contract(
                "module.schema.json",
                _json_text(source_document),
            )
        except ContractError:
            raise CatalogError("v3-module-schema-invalid") from None
        if module["id"] != declaration["id"]:
            raise CatalogError("v3-catalog-source-id-mismatch")
        if module["id"] in module_ids:
            raise CatalogError("v3-catalog-duplicate-id")
        module_ids.add(module["id"])
        modules.append(module)

    for module_ids_in_domain in domain_modules.values():
        for module_id in module_ids_in_domain:
            if module_id not in module_ids:
                raise CatalogError("v3-domain-module-unknown")
    _validate_module_graph(modules)
    domains.sort(key=lambda item: item["id"])
    modules.sort(key=lambda item: item["id"])
    catalog_without_hash = {
        "schemaVersion": 3,
        "domains": domains,
        "modules": modules,
    }
    catalog_hash = _canonical_hash(catalog_without_hash)
    catalog = {**catalog_without_hash, "catalogHash": catalog_hash}
    try:
        load_contract("catalog.schema.json", _canonical_json(catalog).decode("utf-8"))
    except ContractError:
        raise CatalogError("v3-catalog-schema-invalid") from None
    envelope = {
        "schemaVersion": 3,
        "catalog": catalog,
        "catalogHash": catalog_hash,
    }
    return _issue_compiled_catalog(
        envelope, _canonical_json(envelope), catalog_hash,
    )


def _canonical_json(value: object) -> bytes:
    return _json_text(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _json_text(
    value: object,
    *,
    sort_keys: bool = False,
    separators: tuple[str, str] | None = None,
) -> str:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            sort_keys=sort_keys,
            separators=separators,
        )
    except (OverflowError, RecursionError, TypeError, ValueError):
        raise CatalogError("v3-json-serialization-invalid") from None


def _canonical_hash(value: object) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(value)).hexdigest()


def _read_bytes(
    path: Path,
    limit: int,
    trusted_root: Path,
) -> bytes:
    try:
        parent_before = _parent_identity_snapshot(path, trusted_root)
        before = path.lstat()
        if _metadata_is_reparse(before) or before.st_size > limit:
            raise CatalogError("v3-yaml-resource-limit" if before.st_size > limit else "v3-catalog-ref-reparse")
        if not stat.S_ISREG(before.st_mode):
            raise CatalogError("v3-yaml-path-changed")
        with path.open("rb") as source:
            opened = os.fstat(source.fileno())
            if not _same_identity(before, opened):
                raise CatalogError("v3-yaml-path-changed")
            data = source.read(limit + 1)
            after_read = os.fstat(source.fileno())
            after_path = path.lstat()
            parent_after = _parent_identity_snapshot(path, trusted_root)
            if _metadata_is_reparse(after_path):
                raise CatalogError("v3-catalog-ref-reparse")
            if (
                not _same_identity(opened, after_read)
                or not _same_identity(after_read, after_path)
                or not _same_parent_identities(parent_before, parent_after)
            ):
                raise CatalogError("v3-yaml-path-changed")
        if len(data) > limit:
            raise CatalogError("v3-yaml-resource-limit")
        return data
    except CatalogError:
        raise
    except (OSError, ValueError):
        raise CatalogError("v3-catalog-ref-unresolved") from None


def _parent_identity_snapshot(
    path: Path,
    trusted_root: Path,
) -> tuple[os.stat_result, ...]:
    root = trusted_root
    try:
        relative_parent = path.parent.relative_to(root)
    except ValueError:
        raise CatalogError("v3-yaml-path-changed") from None
    current = root
    parents = [current]
    for part in relative_parent.parts:
        current = current / part
        parents.append(current)
    snapshot = []
    for parent in parents:
        metadata = parent.lstat()
        if _metadata_is_reparse(metadata) or not stat.S_ISDIR(metadata.st_mode):
            raise CatalogError("v3-yaml-path-changed")
        snapshot.append(metadata)
    return tuple(snapshot)


def _same_identity(first: os.stat_result, second: os.stat_result) -> bool:
    return (
        stat.S_IFMT(first.st_mode) == stat.S_IFMT(second.st_mode)
        and os.path.samestat(first, second)
    )


def _same_parent_identities(
    before: tuple[os.stat_result, ...],
    after: tuple[os.stat_result, ...],
) -> bool:
    return len(before) == len(after) and all(
        _same_identity(first, second) for first, second in zip(before, after)
    )


def _load_yaml_file(
    path: Path,
    limit: int,
    trusted_root: Path,
) -> object:
    return _load_yaml_bytes(_read_bytes(path, limit, trusted_root))


def _load_yaml_bytes(data: bytes) -> object:
    try:
        text = data.decode("utf-8")
    except UnicodeError:
        raise CatalogError("v3-yaml-invalid") from None
    try:
        document = yaml.load(text, Loader=_StrictLoader)
        _validate_json_compatible(document)
        return document
    except _DuplicateKeyError:
        raise CatalogError("v3-yaml-duplicate-key") from None
    except _AliasError:
        raise CatalogError("v3-yaml-alias-forbidden") from None
    except (_NonJsonYamlError, TypeError):
        raise CatalogError("v3-yaml-non-json-compatible") from None
    except yaml.composer.ComposerError as error:
        if "single document" in str(error).lower():
            raise CatalogError("v3-yaml-multiple-documents") from None
        raise CatalogError("v3-yaml-invalid") from None
    except (RecursionError, yaml.YAMLError, ValueError):
        raise CatalogError("v3-yaml-invalid") from None


def _validate_json_compatible(value: object) -> None:
    pending = [value]
    while pending:
        current = pending.pop()
        if current is None or type(current) in {bool, int, str}:
            continue
        if type(current) is float:
            if math.isfinite(current):
                continue
            raise _NonJsonYamlError
        if type(current) is list:
            pending.extend(current)
            continue
        if type(current) is dict:
            if any(type(key) is not str for key in current):
                raise _NonJsonYamlError
            pending.extend(current.values())
            continue
        raise _NonJsonYamlError


def _is_reparse_point(path: Path) -> bool:
    return _metadata_is_reparse(path.lstat())


def _metadata_is_reparse(metadata: os.stat_result) -> bool:
    return stat.S_ISLNK(metadata.st_mode) or bool(
        getattr(metadata, "st_file_attributes", 0) & _REPARSE_POINT
    )


def _v3_index_path(source: object) -> Path:
    if source is None:
        source = Path(__file__).resolve().parents[3] / "catalog" / "v3" / "index.yaml"
    try:
        path = Path(source)
        if (
            path.name != "index.yaml"
            or path.parent.name != "v3"
            or path.parent.parent.name != "catalog"
        ):
            raise CatalogError("v3-catalog-path-invalid")
        current = path.parent.parent.parent
        for part in (current, current / "catalog", current / "catalog" / "v3", path):
            if _is_reparse_point(part):
                raise CatalogError("v3-catalog-path-reparse")
        if not path.is_file():
            raise CatalogError("v3-catalog-path-invalid")
        return path
    except CatalogError:
        raise
    except (OSError, TypeError, ValueError):
        raise CatalogError("v3-catalog-path-invalid") from None


def _safe_ref(catalog_root: Path, reference: object) -> Path:
    if type(reference) is not str or not reference or "\\" in reference:
        raise CatalogError("v3-catalog-ref-invalid")
    windows = PureWindowsPath(reference)
    parts = tuple(reference.split("/"))
    if (
        windows.is_absolute()
        or windows.drive
        or windows.root
        or ":" in reference
        or any(part in {"", ".", ".."} for part in parts)
    ):
        raise CatalogError("v3-catalog-ref-invalid")
    target = catalog_root.joinpath(*parts)
    try:
        current = catalog_root
        for part in parts:
            current = current / part
            if _is_reparse_point(current):
                raise CatalogError("v3-catalog-ref-reparse")
        for part in (catalog_root, target):
            if _is_reparse_point(part):
                raise CatalogError("v3-catalog-ref-reparse")
        if not target.is_file():
            raise CatalogError("v3-catalog-ref-unresolved")
        target.resolve(strict=True).relative_to(catalog_root.resolve(strict=True))
    except CatalogError:
        raise
    except (OSError, ValueError):
        raise CatalogError("v3-catalog-ref-invalid") from None
    return target


def _verify_hash(source_bytes: bytes, expected: object) -> None:
    if type(expected) is not str or not re.fullmatch(r"sha256:[0-9a-f]{64}", expected):
        raise CatalogError("v3-catalog-source-hash-invalid")
    actual = _hash_bytes(source_bytes)
    if actual != expected:
        raise CatalogError("v3-catalog-source-hash-mismatch")


def _hash_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _require_fields(document: dict[object, object], fields: set[str], reason: str) -> None:
    if set(document) - fields:
        raise CatalogError(reason)


def _valid_id(value: object) -> bool:
    return type(value) is str and _IDENTIFIER.fullmatch(value) is not None


def _read_refs(values: object) -> list[dict[str, str]]:
    if not isinstance(values, list):
        raise CatalogError("v3-catalog-schema-invalid")
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, dict):
            raise CatalogError("v3-catalog-schema-invalid")
        _require_fields(value, _REF_FIELDS, "v3-catalog-unknown-field")
        if set(value) != _REF_FIELDS or not _valid_id(value.get("id")):
            raise CatalogError("v3-catalog-schema-invalid")
        if value["id"] in seen:
            raise CatalogError("v3-catalog-duplicate-id")
        seen.add(value["id"])
        result.append({"id": value["id"], "ref": value["ref"], "hash": value["hash"]})
    return result


def _validate_domain(domain: object) -> None:
    if not isinstance(domain, dict):
        raise CatalogError("v3-domain-schema-invalid")
    _require_fields(domain, _DOMAIN_FIELDS, "v3-domain-unknown-field")
    if (
        set(domain) != _DOMAIN_FIELDS
        or domain.get("schemaVersion") != 3
        or not _valid_id(domain.get("id"))
        or not isinstance(domain.get("modules"), list)
        or any(not _valid_id(item) for item in domain["modules"])
        or len(domain["modules"]) != len(set(domain["modules"]))
    ):
        raise CatalogError("v3-domain-schema-invalid")


def _validate_module_graph(modules: list[dict[str, Any]]) -> None:
    ids = {module["id"] for module in modules}
    for module in modules:
        for field in ("dependencies", "conflicts"):
            if any(item not in ids for item in module[field]):
                raise CatalogError("v3-catalog-unknown-module")
            if module["id"] in module[field]:
                raise CatalogError("v3-catalog-self-reference")
        for conflict in module["conflicts"]:
            other = next(item for item in modules if item["id"] == conflict)
            if module["id"] not in other["conflicts"]:
                raise CatalogError("v3-catalog-conflict-asymmetric")
    dependencies = {module["id"]: set(module["dependencies"]) for module in modules}
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(module_id: str) -> None:
        if module_id in visiting:
            raise CatalogError("v3-catalog-dependency-cycle")
        if module_id in visited:
            return
        visiting.add(module_id)
        for dependency in dependencies[module_id]:
            visit(dependency)
        visiting.remove(module_id)
        visited.add(module_id)

    for module_id in sorted(dependencies):
        visit(module_id)
