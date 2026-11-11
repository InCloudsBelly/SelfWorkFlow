# 只读参考：provider-descriptor.schema.json

此处为资料或模板，不提供可执行程序；实际工具须独立配置。

````text
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://selfworkflow.local/schemas/v3/provider-descriptor.schema.json",
  "title": "SelfWorkFlow V3 provider descriptor",
  "type": "object", "additionalProperties": false,
  "required": ["schemaVersion", "providerId", "kind", "capabilities", "sourceIdentityRef", "license", "adapterRef", "adapterHash", "operations", "supportMatrixRef", "dataBoundary", "remoteSourceTransfer"],
  "properties": {
    "schemaVersion": {"const": 3}, "providerId": {"$ref": "#/$defs/id"},
    "kind": {"enum": ["prompt-skill", "mcp-provider", "cli-provider", "reference-pack", "agent-native"]},
    "capabilities": {"type": "array", "minItems": 1, "maxItems": 256, "uniqueItems": true, "items": {"$ref": "#/$defs/id"}},
    "sourceIdentityRef": {"$ref": "#/$defs/id"}, "license": {"type": "object", "additionalProperties": false, "required": ["spdxId"], "properties": {"spdxId": {"type": "string", "minLength": 1, "maxLength": 128}, "noticeHash": {"$ref": "#/$defs/hash"}}},
    "adapterRef": {"$ref": "#/$defs/id"}, "adapterHash": {"$ref": "#/$defs/hash"}, "operations": {"type": "array", "minItems": 1, "maxItems": 128, "items": {"$ref": "#/$defs/operation"}},
    "supportMatrixRef": {"$ref": "#/$defs/id"}, "dataBoundary": {"enum": ["local-only", "remote-approved", "remote-required"]}, "remoteSourceTransfer": {"enum": ["forbidden", "explicit-only", "allowed"]}
  },
  "$defs": {
    "id": {"type": "string", "pattern": "^[a-z0-9][a-z0-9._-]{0,127}$"}, "hash": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"},
    "operation": {"type": "object", "additionalProperties": false, "required": ["operationId", "triggerLevel", "risk", "sideEffects", "ownershipDomain", "mutationTargets", "argvTemplate", "cwdPolicy", "envAllowlist", "networkPolicy", "lockScope", "timeoutSeconds", "outputLimitBytes", "preconditions", "verification", "rollback"], "properties": {
      "operationId": {"$ref": "#/$defs/id"}, "triggerLevel": {"enum": ["automatic-readonly", "recommend-before-use", "manual-only"]}, "risk": {"enum": ["low", "medium", "high", "critical"]}, "sideEffects": {"type": "array", "maxItems": 32, "uniqueItems": true, "items": {"type": "string", "minLength": 1, "maxLength": 128}}, "ownershipDomain": {"enum": ["selfworkflow-managed", "user-owned", "external-service"]}, "mutationTargets": {"type": "array", "maxItems": 64, "uniqueItems": true, "items": {"enum": ["exact-file", "directory-subtree", "managed-state-root", "process", "service"]}}, "argvTemplate": {"type": "string", "minLength": 1, "maxLength": 4096}, "cwdPolicy": {"enum": ["workspace-root", "provider-root", "managed-root", "none"]}, "envAllowlist": {"type": "array", "maxItems": 128, "uniqueItems": true, "items": {"type": "string", "pattern": "^[A-Z][A-Z0-9_]{0,127}$"}}, "networkPolicy": {"enum": ["none", "local-only", "explicit-approved", "allowed"]}, "lockScope": {"enum": ["none", "provider", "provider-project"]}, "timeoutSeconds": {"type": "integer", "minimum": 1, "maximum": 86400}, "outputLimitBytes": {"type": "integer", "minimum": 1, "maximum": 1073741824}, "preconditions": {"type": "array", "maxItems": 64, "items": {"$ref": "#/$defs/id"}}, "verification": {"type": "array", "minItems": 1, "maxItems": 64, "items": {"$ref": "#/$defs/id"}}, "rollback": {"enum": ["none", "declared", "transactional"]}
    }}
  }
}

````
