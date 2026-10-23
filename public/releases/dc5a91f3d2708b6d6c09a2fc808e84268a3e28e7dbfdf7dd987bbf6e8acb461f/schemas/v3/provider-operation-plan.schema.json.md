# 只读参考：provider-operation-plan.schema.json

此处为资料或模板，不提供可执行程序；实际工具须独立配置。

````text
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://selfworkflow.local/schemas/v3/provider-operation-plan.schema.json",
  "title": "SelfWorkFlow V3 provider operation plan",
  "type": "object",
  "additionalProperties": false,
  "required": ["schemaVersion", "operationPlanHash", "planHash", "providerId", "operationId", "bindingSnapshotHash", "adapterHash", "commandRegistryHash", "commandTemplateHash", "canonicalTargetHash", "containmentRootHash", "adapterRenderHash", "networkPolicy", "sideEffectClass", "timeoutSeconds", "outputLimitBytes", "mutationTargets", "commandSpec", "executionNonce", "attemptRef", "operationAuthorizationSubjectHash", "canonicalProjectRootHash", "ownershipDomain"],
  "properties": {
    "schemaVersion": {"const": 3},
    "operationPlanHash": {"$ref": "#/$defs/hash"},
    "planHash": {"$ref": "#/$defs/hash"},
    "providerId": {"$ref": "#/$defs/id"},
    "operationId": {"enum": ["inspect", "initialize-index", "sync-incremental", "rebuild-index", "upgrade-managed-adapter", "repair-managed-state"]},
    "bindingSnapshotHash": {"$ref": "#/$defs/hash"},
    "adapterHash": {"$ref": "#/$defs/hash"},
    "commandRegistryHash": {"$ref": "#/$defs/hash"},
    "commandTemplateHash": {"$ref": "#/$defs/hash"},
    "canonicalTargetHash": {"$ref": "#/$defs/hash"},
    "containmentRootHash": {"$ref": "#/$defs/hash"},
    "adapterRenderHash": {"$ref": "#/$defs/hash"},
    "networkPolicy": {"const": "none"},
    "sideEffectClass": {"enum": ["none", "local-write"]},
    "timeoutSeconds": {"type": "integer", "minimum": 1, "maximum": 86400},
    "outputLimitBytes": {"type": "integer", "minimum": 1, "maximum": 1073741824},
    "mutationTargets": {"type": "array", "maxItems": 64, "items": {"$ref": "#/$defs/target"}},
    "commandSpec": {"$ref": "#/$defs/command"},
    "executionNonce": {"$ref": "#/$defs/id"},
    "attemptRef": {"$ref": "#/$defs/id"},
    "approvalReceiptRef": {"$ref": "#/$defs/id"},
    "approvalReceiptHash": {"$ref": "#/$defs/hash"},
    "approvalReceipt": {"type": "object"},
    "operationAuthorizationSubjectHash": {"$ref": "#/$defs/hash"},
    "machineAuthorizationHash": {"$ref": "#/$defs/hash"},
    "canonicalProjectRootHash": {"$ref": "#/$defs/hash"},
    "ownershipDomain": {"enum": ["selfworkflow-managed", "user-owned"]}
  },
  "$defs": {
    "id": {"type": "string", "pattern": "^[a-z0-9][a-z0-9._-]{0,127}$"},
    "hash": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"},
    "target": {
      "type": "object", "additionalProperties": false,
      "required": ["targetKind", "targetId", "canonicalTargetHash", "mutationTargetHash", "containmentRootHash", "recursion", "reparsePolicy", "allowedActions", "evidenceRequired"],
      "properties": {
        "targetKind": {"const": "managed-state-root"},
        "targetId": {"type": "string", "minLength": 1, "maxLength": 512},
        "canonicalTargetHash": {"$ref": "#/$defs/hash"},
        "mutationTargetHash": {"$ref": "#/$defs/hash"},
        "containmentRootHash": {"$ref": "#/$defs/hash"},
        "recursion": {"const": "none"},
        "reparsePolicy": {"const": "reject"},
        "allowedActions": {"type": "array", "minItems": 1, "maxItems": 1, "uniqueItems": true, "items": {"enum": ["initialize", "sync", "rebuild", "upgrade", "repair"]}},
        "evidenceRequired": {"const": true}
      }
    },
    "command": {
      "type": "object", "additionalProperties": false,
      "required": ["commandSpecHash", "registryHash", "templateHash", "providerId", "bindingSnapshotHash", "adapterHash", "operationId", "argv", "env", "canonicalProjectRoot", "cwd", "cwdPolicy", "sideEffectClass", "networkPolicy"],
      "properties": {
        "commandSpecHash": {"$ref": "#/$defs/hash"}, "registryHash": {"$ref": "#/$defs/hash"}, "templateHash": {"$ref": "#/$defs/hash"},
        "providerId": {"$ref": "#/$defs/id"}, "bindingSnapshotHash": {"$ref": "#/$defs/hash"}, "adapterHash": {"$ref": "#/$defs/hash"}, "operationId": {"$ref": "#/$defs/id"},
        "argv": {"type": "array", "minItems": 1, "maxItems": 256, "items": {"type": "string", "minLength": 1, "maxLength": 4096}},
        "env": {"type": "object", "maxProperties": 64, "additionalProperties": {"type": "string", "maxLength": 8192}},
        "canonicalProjectRoot": {"type": "string", "minLength": 1, "maxLength": 32767}, "cwd": {"type": "string", "minLength": 1, "maxLength": 32767},
        "cwdPolicy": {"const": "project-root"}, "sideEffectClass": {"enum": ["none", "local-write"]}, "networkPolicy": {"const": "none"}
      }
    }
  }
}

````
