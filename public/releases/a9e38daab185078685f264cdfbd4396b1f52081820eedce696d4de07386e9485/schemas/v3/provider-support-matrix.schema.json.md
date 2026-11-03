# 只读参考：provider-support-matrix.schema.json

此处为资料或模板，不提供可执行程序；实际工具须独立配置。

````text
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://selfworkflow.local/schemas/v3/provider-support-matrix.schema.json",
  "title": "SelfWorkFlow V3 provider support matrix",
  "type": "object", "additionalProperties": false,
  "required": ["schemaVersion", "providerId", "entries", "matrixHash"],
  "properties": {
    "schemaVersion": {"const": 3}, "providerId": {"$ref": "#/$defs/id"},
    "entries": {"type": "array", "maxItems": 4096, "items": {"$ref": "#/$defs/entry"}},
    "matrixHash": {"$ref": "#/$defs/hash"}
  },
  "$defs": {
    "id": {"type": "string", "pattern": "^[a-z0-9][a-z0-9._-]{0,127}$"},
    "hash": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"},
    "evidenceRef": {"type": "string", "pattern": "^(?:sha256:[0-9a-f]{64}|ref:[a-z0-9][a-z0-9._/-]{0,255})$"},
    "evidence": {
      "type": "object", "additionalProperties": false,
      "properties": {
        "source": {"$ref": "#/$defs/evidenceRef"}, "adapter": {"$ref": "#/$defs/evidenceRef"},
        "positive": {"$ref": "#/$defs/evidenceRef"}, "false": {"$ref": "#/$defs/evidenceRef"},
        "conflict": {"$ref": "#/$defs/evidenceRef"}, "failure": {"$ref": "#/$defs/evidenceRef"},
        "contextCost": {"$ref": "#/$defs/evidenceRef"}, "nativeValidation": {"$ref": "#/$defs/evidenceRef"}
      }
    },
    "entry": {
      "type": "object", "additionalProperties": false,
      "required": ["entryId", "entryHash", "capabilityId", "operationId", "platform", "adapterVersion", "adapterHash", "sourceIdentityRef", "sourceIdentityHash", "state", "observedAt", "evidence"],
      "properties": {
        "entryId": {"$ref": "#/$defs/id"}, "entryHash": {"$ref": "#/$defs/hash"},
        "capabilityId": {"$ref": "#/$defs/id"}, "operationId": {"$ref": "#/$defs/id"},
        "platform": {"type": "string", "pattern": "^[a-z0-9][a-z0-9._-]{0,63}$"},
        "adapterVersion": {"type": "string", "minLength": 1, "maxLength": 128}, "adapterHash": {"$ref": "#/$defs/hash"},
        "sourceIdentityRef": {"$ref": "#/$defs/id"}, "sourceIdentityHash": {"$ref": "#/$defs/hash"},
        "state": {"enum": ["supported", "unverified", "unsupported", "needs-revalidation"]},
        "observedAt": {"type": "string", "format": "utc-date-time"}, "validUntil": {"type": "string", "format": "utc-date-time"},
        "evidence": {"$ref": "#/$defs/evidence"}, "notes": {"type": "string", "maxLength": 2000}
      },
      "allOf": [{"if": {"properties": {"state": {"const": "supported"}}}, "then": {"required": ["validUntil"], "properties": {"evidence": {"required": ["source", "adapter", "positive", "false", "conflict", "failure", "contextCost", "nativeValidation"]}}}}]
    }
  }
}

````
