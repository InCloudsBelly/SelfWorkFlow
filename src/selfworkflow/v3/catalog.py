"""Strict, deterministic compilation for the independent V3 catalog."""

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
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


@dataclass(frozen=True)
class CompiledCatalog:
    document: dict[str, Any]
    content: bytes
    catalog_hash: str


def compile_catalog(source: object = None) -> CompiledCatalog:
    index = _v3_index_path(source)
    root = index.parents[2]
    catalog_root = root / "catalog" / "v3"
    document = _load_yaml_file(index, _MAX_DOCUMENT_BYTES)
    if not isinstance(document, dict):
        raise CatalogError("v3-catalog-root-invalid")
    _require_fields(document, _INDEX_FIELDS, "v3-catalog-unknown-field")
    if document.get("schemaVersion") != 3:
        raise CatalogError("v3-catalog-version-mismatch")
    if not isinstance(document.get("domains"), list) or not isinstance(document.get("modules"), list):
        raise CatalogError("v3-catalog-schema-invalid")

    domain_declarations = _read_refs(document["domains"], "domains")
    module_declarations = _read_refs(document["modules"], "modules")
    domains: list[dict[str, Any]] = []
    domain_modules: dict[str, list[str]] = {}
    for declaration in domain_declarations:
        target = _safe_ref(catalog_root, declaration["ref"])
        _verify_hash(target, declaration["hash"])
        domain = _load_yaml_file(target, _MAX_SOURCE_BYTES)
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
        _verify_hash(target, declaration["hash"])
        try:
            source_document = _load_yaml_file(target, _MAX_SOURCE_BYTES)
            module = load_contract(
                "module.schema.json",
                json.dumps(source_document, ensure_ascii=False),
            )
        except (ContractError, UnicodeError):
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
    return CompiledCatalog(envelope, _canonical_json(envelope), catalog_hash)


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _canonical_hash(value: object) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(value)).hexdigest()


def _read_bytes(path: Path, limit: int) -> bytes:
    try:
        metadata = path.lstat()
        if _is_reparse_point(path) or metadata.st_size > limit:
            raise CatalogError("v3-yaml-resource-limit" if metadata.st_size > limit else "v3-catalog-ref-reparse")
        return path.read_bytes()
    except CatalogError:
        raise
    except (OSError, ValueError):
        raise CatalogError("v3-catalog-ref-unresolved") from None


def _load_yaml_file(path: Path, limit: int) -> object:
    try:
        text = _read_bytes(path, limit).decode("utf-8")
    except UnicodeError:
        raise CatalogError("v3-yaml-invalid") from None
    try:
        return yaml.load(text, Loader=_StrictLoader)
    except _DuplicateKeyError:
        raise CatalogError("v3-yaml-duplicate-key") from None
    except _AliasError:
        raise CatalogError("v3-yaml-alias-forbidden") from None
    except yaml.composer.ComposerError as error:
        if "single document" in str(error).lower():
            raise CatalogError("v3-yaml-multiple-documents") from None
        raise CatalogError("v3-yaml-invalid") from None
    except (RecursionError, yaml.YAMLError, ValueError):
        raise CatalogError("v3-yaml-invalid") from None


def _is_reparse_point(path: Path) -> bool:
    metadata = path.lstat()
    return path.is_symlink() or bool(
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


def _verify_hash(path: Path, expected: object) -> None:
    if type(expected) is not str or not re.fullmatch(r"sha256:[0-9a-f]{64}", expected):
        raise CatalogError("v3-catalog-source-hash-invalid")
    actual = _hash_bytes(_read_bytes(path, _MAX_SOURCE_BYTES))
    if actual != expected:
        raise CatalogError("v3-catalog-source-hash-mismatch")


def _hash_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _require_fields(document: dict[object, object], fields: set[str], reason: str) -> None:
    if set(document) - fields:
        raise CatalogError(reason)


def _valid_id(value: object) -> bool:
    return type(value) is str and _IDENTIFIER.fullmatch(value) is not None


def _read_refs(values: object, collection: str) -> list[dict[str, str]]:
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
