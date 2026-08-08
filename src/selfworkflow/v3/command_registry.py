"""Content-addressed, host-trusted command templates for Provider execution.

The registry is serialized and revalidated at every trust boundary.  The Python
wrapper is convenience only; it is not the security boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
import ntpath
import os
import re
from typing import Any, Iterable, Mapping

from selfworkflow.v3.hashing import clone, content_hash, require_hash


class CommandRegistryError(ValueError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_PLACEHOLDER = re.compile(r"^\{(?:projectRoot|operationId|param:([a-z][a-z0-9._-]{0,63}))\}$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_SHELL_EXECUTABLES = {
    "cmd", "cmd.exe", "command.com", "powershell", "powershell.exe",
    "pwsh", "pwsh.exe", "sh", "sh.exe", "bash", "bash.exe",
    "wscript", "wscript.exe", "cscript", "cscript.exe",
}
_SHELL_EXTENSIONS = {".bat", ".cmd", ".ps1"}
_DANGEROUS_ENV = {
    "PATH", "PATHEXT", "COMSPEC", "PYTHONPATH", "PYTHONHOME", "NODE_OPTIONS",
    "PSMODULEPATH", "LD_PRELOAD", "LD_LIBRARY_PATH", "DYLD_INSERT_LIBRARIES",
    "DYLD_LIBRARY_PATH", "RUBYOPT", "PERL5OPT", "PROMPT", "CDPATH",
    "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "APPDATA", "LOCALAPPDATA",
    "USERPROFILE", "HOME", "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE",
    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
}


def _safe_id(value: object, reason: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise CommandRegistryError(reason)
    return value


def _safe_executable(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > 32767 or _CONTROL.search(value):
        raise CommandRegistryError("trusted-command-executable-invalid")
    if not os.path.isabs(value):
        raise CommandRegistryError("trusted-command-executable-not-absolute")
    basename = ntpath.basename(value).lower()
    if basename in _SHELL_EXECUTABLES or ntpath.splitext(basename)[1] in _SHELL_EXTENSIONS:
        raise CommandRegistryError("trusted-command-shell-unsupported")
    return os.path.normpath(value)


def _safe_env_names(values: Iterable[str]) -> list[str]:
    result = sorted(set(values))
    for name in result:
        if (
            not isinstance(name, str)
            or not re.fullmatch(r"[A-Z][A-Z0-9_]{0,127}", name)
            or name.upper() in _DANGEROUS_ENV
        ):
            raise CommandRegistryError("trusted-command-env-unsafe")
    return result


def _validate_template(document: Mapping[str, Any]) -> dict[str, Any]:
    material = clone(dict(document))
    required = {
        "schemaVersion", "templateHash", "templateId", "providerId",
        "bindingSnapshotHash", "adapterHash", "operationId", "sideEffectClass",
        "executable", "argvTemplate", "parameterNames", "envAllowlist", "cwdPolicy",
    }
    if set(material) != required or material.get("schemaVersion") != 3:
        raise CommandRegistryError("trusted-command-template-invalid")
    for key in ("templateId", "providerId", "operationId"):
        _safe_id(material.get(key), "trusted-command-template-invalid")
    for key in ("bindingSnapshotHash", "adapterHash"):
        try:
            require_hash(material.get(key))
        except Exception:
            raise CommandRegistryError("trusted-command-template-invalid") from None
    if material.get("sideEffectClass") not in {"none", "local-write"}:
        raise CommandRegistryError("network-unsupported")
    executable = _safe_executable(material.get("executable"))
    if material.get("cwdPolicy") != "project-root":
        raise CommandRegistryError("trusted-command-cwd-policy-unsupported")
    parameter_names = material.get("parameterNames")
    if not isinstance(parameter_names, list) or len(set(parameter_names)) != len(parameter_names):
        raise CommandRegistryError("trusted-command-parameters-invalid")
    for name in parameter_names:
        _safe_id(name, "trusted-command-parameters-invalid")
    argv_template = material.get("argvTemplate")
    if not isinstance(argv_template, list) or not argv_template or len(argv_template) > 256:
        raise CommandRegistryError("trusted-command-template-invalid")
    if argv_template[0] != executable:
        raise CommandRegistryError("trusted-command-executable-drift")
    used: set[str] = set()
    for index, token in enumerate(argv_template):
        if not isinstance(token, str) or not token or len(token) > 4096 or _CONTROL.search(token):
            raise CommandRegistryError("trusted-command-template-invalid")
        match = _PLACEHOLDER.fullmatch(token)
        if "{" in token or "}" in token:
            if match is None:
                raise CommandRegistryError("trusted-command-placeholder-invalid")
            if match.group(1):
                used.add(match.group(1))
        elif index == 0 and token != executable:
            raise CommandRegistryError("trusted-command-executable-drift")
    if used != set(parameter_names):
        raise CommandRegistryError("trusted-command-parameters-invalid")
    material["envAllowlist"] = _safe_env_names(material.get("envAllowlist", ()))
    expected = content_hash({key: value for key, value in material.items() if key != "templateHash"})
    if material.get("templateHash") != expected:
        raise CommandRegistryError("trusted-command-template-hash-invalid")
    return material


@dataclass(frozen=True)
class AdapterCommandTemplate:
    _document: dict[str, Any]

    @property
    def document(self) -> dict[str, Any]:
        return clone(self._document)

    @property
    def template_hash(self) -> str:
        return self._document["templateHash"]


def build_adapter_command_template(
    *, template_id: str, provider_id: str, binding_snapshot_hash: str,
    adapter_hash: str, operation_id: str, side_effect_class: str,
    executable: str, argv_template: Iterable[str],
    parameter_names: Iterable[str] = (), env_allowlist: Iterable[str] = (),
    cwd_policy: str = "project-root",
) -> AdapterCommandTemplate:
    body: dict[str, Any] = {
        "schemaVersion": 3,
        "templateId": template_id,
        "providerId": provider_id,
        "bindingSnapshotHash": binding_snapshot_hash,
        "adapterHash": adapter_hash,
        "operationId": operation_id,
        "sideEffectClass": side_effect_class,
        "executable": os.path.normpath(executable),
        "argvTemplate": list(argv_template),
        "parameterNames": sorted(set(parameter_names)),
        "envAllowlist": sorted(set(env_allowlist)),
        "cwdPolicy": cwd_policy,
    }
    body["templateHash"] = content_hash(body)
    return AdapterCommandTemplate(_validate_template(body))


def validate_adapter_command_template(document: Mapping[str, Any]) -> None:
    _validate_template(document)


@dataclass(frozen=True)
class TrustedCommandRegistry:
    _document: dict[str, Any]

    @property
    def document(self) -> dict[str, Any]:
        return clone(self._document)

    @property
    def registry_hash(self) -> str:
        return self._document["registryHash"]

    @property
    def trust_source(self) -> str:
        return self._document["trustSource"]

    def resolve(
        self, *, template_id: str, provider_id: str, binding_snapshot_hash: str,
        adapter_hash: str, operation_id: str, side_effect_class: str,
    ) -> AdapterCommandTemplate:
        validate_trusted_command_registry(self._document)
        matches = [item for item in self._document["templates"] if all((
            item["templateId"] == template_id,
            item["providerId"] == provider_id,
            item["bindingSnapshotHash"] == binding_snapshot_hash,
            item["adapterHash"] == adapter_hash,
            item["operationId"] == operation_id,
            item["sideEffectClass"] == side_effect_class,
        ))]
        if len(matches) != 1:
            raise CommandRegistryError("trusted-command-template-not-found")
        return AdapterCommandTemplate(_validate_template(matches[0]))


def build_trusted_command_registry(
    templates: Iterable[AdapterCommandTemplate | Mapping[str, Any]], *,
    issuer_id: str = "host-command-authority", trust_source: str = "host-attested",
) -> TrustedCommandRegistry:
    if trust_source not in {"host-attested", "test-fixture"}:
        raise CommandRegistryError("trusted-command-registry-source-invalid")
    _safe_id(issuer_id, "trusted-command-registry-issuer-invalid")
    items = [
        _validate_template(item.document if isinstance(item, AdapterCommandTemplate) else item)
        for item in templates
    ]
    items.sort(key=lambda item: item["templateId"])
    if not items or len({item["templateId"] for item in items}) != len(items):
        raise CommandRegistryError("trusted-command-template-duplicate")
    body: dict[str, Any] = {
        "schemaVersion": 3,
        "issuerId": issuer_id,
        "trustSource": trust_source,
        "templates": items,
    }
    body["registryHash"] = content_hash(body)
    validate_trusted_command_registry(body)
    return TrustedCommandRegistry(clone(body))


def validate_trusted_command_registry(document: Mapping[str, Any], *, production: bool = False) -> None:
    material = clone(dict(document))
    if set(material) != {"schemaVersion", "registryHash", "issuerId", "trustSource", "templates"}:
        raise CommandRegistryError("trusted-command-registry-invalid")
    if material.get("schemaVersion") != 3:
        raise CommandRegistryError("trusted-command-registry-invalid")
    _safe_id(material.get("issuerId"), "trusted-command-registry-issuer-invalid")
    if material.get("trustSource") not in {"host-attested", "test-fixture"}:
        raise CommandRegistryError("trusted-command-registry-source-invalid")
    if production and material["trustSource"] == "test-fixture":
        raise CommandRegistryError("test-command-registry-rejected")
    templates = material.get("templates")
    if not isinstance(templates, list) or not templates:
        raise CommandRegistryError("trusted-command-registry-invalid")
    validated = [_validate_template(item) for item in templates]
    if validated != sorted(validated, key=lambda item: item["templateId"]):
        raise CommandRegistryError("trusted-command-registry-order-invalid")
    if len({item["templateId"] for item in validated}) != len(validated):
        raise CommandRegistryError("trusted-command-template-duplicate")
    expected = content_hash({key: value for key, value in material.items() if key != "registryHash"})
    if material.get("registryHash") != expected:
        raise CommandRegistryError("trusted-command-registry-hash-invalid")


def render_command(
    registry: TrustedCommandRegistry, *, template_id: str, provider_id: str,
    binding_snapshot_hash: str, adapter_hash: str, operation_id: str,
    side_effect_class: str, canonical_project_root: str,
    parameters: Mapping[str, str] | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    template = registry.resolve(
        template_id=template_id,
        provider_id=provider_id,
        binding_snapshot_hash=binding_snapshot_hash,
        adapter_hash=adapter_hash,
        operation_id=operation_id,
        side_effect_class=side_effect_class,
    ).document
    supplied = dict(parameters or {})
    if set(supplied) != set(template["parameterNames"]):
        raise CommandRegistryError("trusted-command-parameters-invalid")
    for key, value in supplied.items():
        if not isinstance(value, str) or not value or len(value) > 4096 or _CONTROL.search(value):
            raise CommandRegistryError("trusted-command-parameter-invalid")
    environment = dict(env or {})
    if set(environment) - set(template["envAllowlist"]):
        raise CommandRegistryError("trusted-command-env-unsafe")
    _safe_env_names(environment)
    for value in environment.values():
        if not isinstance(value, str) or len(value) > 8192 or _CONTROL.search(value):
            raise CommandRegistryError("trusted-command-env-unsafe")
    argv: list[str] = []
    for token in template["argvTemplate"]:
        match = _PLACEHOLDER.fullmatch(token)
        if token == "{projectRoot}":
            argv.append(canonical_project_root)
        elif token == "{operationId}":
            argv.append(operation_id)
        elif match and match.group(1):
            argv.append(supplied[match.group(1)])
        else:
            argv.append(token)
    command: dict[str, Any] = {
        "registryHash": registry.registry_hash,
        "templateHash": template["templateHash"],
        "providerId": provider_id,
        "bindingSnapshotHash": binding_snapshot_hash,
        "adapterHash": adapter_hash,
        "operationId": operation_id,
        "argv": argv,
        "env": dict(sorted(environment.items())),
        "canonicalProjectRoot": canonical_project_root,
        "cwd": canonical_project_root,
        "cwdPolicy": "project-root",
        "sideEffectClass": side_effect_class,
        "networkPolicy": "none",
    }
    command["commandSpecHash"] = content_hash(command)
    return command


def validate_rendered_command(
    command: Mapping[str, Any], registry: TrustedCommandRegistry, *,
    production: bool,
) -> None:
    validate_trusted_command_registry(registry.document, production=production)
    material = clone(dict(command))
    expected_hash = content_hash({key: value for key, value in material.items() if key != "commandSpecHash"})
    if material.get("commandSpecHash") != expected_hash:
        raise CommandRegistryError("command-spec-hash-invalid")
    template = registry.resolve(
        template_id=next((item["templateId"] for item in registry.document["templates"] if item["templateHash"] == material.get("templateHash")), ""),
        provider_id=material.get("providerId", ""),
        binding_snapshot_hash=material.get("bindingSnapshotHash", ""),
        adapter_hash=material.get("adapterHash", ""),
        operation_id=material.get("operationId", ""),
        side_effect_class=material.get("sideEffectClass", ""),
    ).document
    if material.get("registryHash") != registry.registry_hash:
        raise CommandRegistryError("trusted-command-registry-drift")
    if material.get("cwdPolicy") != "project-root" or material.get("cwd") != material.get("canonicalProjectRoot"):
        raise CommandRegistryError("command-cwd-outside-project")
    if material.get("networkPolicy") != "none" or material.get("sideEffectClass") == "network":
        raise CommandRegistryError("network-unsupported")
    if material.get("argv", [None])[0] != template["executable"]:
        raise CommandRegistryError("trusted-command-executable-drift")
    argv = material.get("argv")
    if not isinstance(argv, list) or len(argv) != len(template["argvTemplate"]):
        raise CommandRegistryError("trusted-command-render-invalid")
    for rendered, token in zip(argv, template["argvTemplate"], strict=True):
        match = _PLACEHOLDER.fullmatch(token)
        if token == "{projectRoot}" and rendered != material.get("canonicalProjectRoot"):
            raise CommandRegistryError("trusted-command-render-invalid")
        if token == "{operationId}" and rendered != material.get("operationId"):
            raise CommandRegistryError("trusted-command-render-invalid")
        if match and match.group(1):
            if not isinstance(rendered, str) or not rendered or len(rendered) > 4096 or _CONTROL.search(rendered):
                raise CommandRegistryError("trusted-command-render-invalid")
        elif match is None and rendered != token:
            raise CommandRegistryError("trusted-command-render-invalid")
    if set(material.get("env", {})) - set(template["envAllowlist"]):
        raise CommandRegistryError("trusted-command-env-unsafe")
    _safe_env_names(material.get("env", {}))
    for value in material.get("env", {}).values():
        if not isinstance(value, str) or len(value) > 8192 or _CONTROL.search(value):
            raise CommandRegistryError("trusted-command-env-unsafe")
