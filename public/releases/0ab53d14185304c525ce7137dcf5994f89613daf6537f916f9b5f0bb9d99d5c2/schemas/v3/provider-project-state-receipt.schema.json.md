# 只读参考：provider-project-state-receipt.schema.json

此处为资料或模板，不提供可执行程序；实际工具须独立配置。

````text
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://selfworkflow.local/schemas/v3/provider-project-state-receipt.schema.json",
  "title": "SelfWorkFlow V3 provider project state receipt",
  "type": "object", "additionalProperties": false,
  "required": ["schemaVersion", "receiptHash", "providerId", "sourceIdentityHash", "canonicalProjectRootHash", "workspaceFingerprintHash", "indexRevision", "health", "sourceContentFresh", "relationshipFresh", "capturedAt", "validUntil", "pendingFiles", "parseFailures"],
  "properties": {
    "schemaVersion": {"const": 3}, "receiptHash": {"$ref": "#/$defs/hash"},
    "providerId": {"$ref": "#/$defs/id"}, "sourceIdentityHash": {"$ref": "#/$defs/hash"},
    "canonicalProjectRootHash": {"$ref": "#/$defs/hash"}, "workspaceFingerprintHash": {"$ref": "#/$defs/hash"},
    "indexRevision": {"type": "string", "minLength": 1, "maxLength": 256},
    "health": {"enum": ["ready", "degraded", "unavailable", "unknown"]},
    "sourceContentFresh": {"enum": ["fresh", "stale", "unknown"]}, "relationshipFresh": {"enum": ["fresh", "stale", "unknown"]},
    "capturedAt": {"type": "string", "format": "utc-date-time"}, "validUntil": {"type": "string", "format": "utc-date-time"},
    "pendingFiles": {"type": "array", "maxItems": 200000, "uniqueItems": true, "items": {"$ref": "#/$defs/projectPath"}},
    "parseFailures": {"type": "array", "maxItems": 200000, "items": {"$ref": "#/$defs/id"}},
    "stateEvidenceRef": {"$ref": "#/$defs/id"}
  },
  "$defs": {
    "id": {"type": "string", "pattern": "^[a-z0-9][a-z0-9._-]{0,127}$"},
    "hash": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"},
    "projectPath": {"type": "string", "minLength": 1, "maxLength": 1024, "pattern": "^(?![A-Za-z]:)(?!/)(?!.*\\\\)(?!.*(?:^|/)\\.\\.?(?:/|$))(?!.*//)(?!.*[ .](?:/|$))[^\\u0000-\\u001f<>:\"|?*]+$"}
  }
}

````
