# 只读参考：diff-signal-set.schema.json

此处为资料或模板，不提供可执行程序；实际工具须独立配置。

````text
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://selfworkflow.local/schemas/v3/diff-signal-set.schema.json",
  "title": "SelfWorkFlow V3 diff signal set",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "schemaVersion", "planHash", "attemptRef", "createdAt", "finalDiffHash",
    "files", "languages", "boundarySignals", "stateSignals", "concurrencySignals",
    "securitySignals", "performanceSignals", "evidenceRefs", "signalSetHash"
  ],
  "properties": {
    "schemaVersion": {"const": 3},
    "planHash": {"$ref": "#/$defs/sha256"},
    "attemptRef": {"$ref": "#/$defs/stableId"},
    "createdAt": {"$ref": "#/$defs/utcTimestamp"},
    "finalDiffHash": {"$ref": "#/$defs/sha256"},
    "files": {
      "type": "array", "minItems": 1, "maxItems": 4096, "uniqueItems": true,
      "items": {"$ref": "#/$defs/file"}
    },
    "languages": {"$ref": "#/$defs/idList"},
    "boundarySignals": {"$ref": "#/$defs/idList"},
    "stateSignals": {"$ref": "#/$defs/idList"},
    "concurrencySignals": {"$ref": "#/$defs/idList"},
    "securitySignals": {"$ref": "#/$defs/idList"},
    "performanceSignals": {"$ref": "#/$defs/idList"},
    "evidenceRefs": {"$ref": "#/$defs/idList"},
    "signalSetHash": {"$ref": "#/$defs/sha256"}
  },
  "$defs": {
    "stableId": {"type": "string", "pattern": "^[a-z0-9][a-z0-9._:-]{0,127}$"},
    "sha256": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"},
    "utcTimestamp": {
      "type": "string", "format": "date-time",
      "pattern": "^\\d{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\\d|3[01])T(?:[01]\\d|2[0-3]):[0-5]\\d:[0-5]\\d(?:\\.\\d+)?Z$"
    },
    "idList": {
      "type": "array", "maxItems": 4096, "uniqueItems": true,
      "items": {"$ref": "#/$defs/stableId"}
    },
    "file": {
      "type": "object", "additionalProperties": false,
      "required": ["path", "status", "language"],
      "properties": {
        "path": {"type": "string", "minLength": 1, "pattern": "^[^\\u0000]+$"},
        "status": {"enum": ["added", "modified", "deleted", "renamed", "copied"]},
        "language": {"$ref": "#/$defs/stableId"}
      }
    }
  }
}

````
