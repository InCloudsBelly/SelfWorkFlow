# 只读参考：review-finding.schema.json

此处为资料或模板，不提供可执行程序；实际工具须独立配置。

````text
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://selfworkflow.local/schemas/v3/review-finding.schema.json",
  "title": "SelfWorkFlow V3 review finding",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "schemaVersion", "planHash", "attemptRef", "createdAt", "finalDiffHash",
    "diffSignalSetHash", "fingerprint", "severity", "rootCauseOwner",
    "detectionPoint", "evidenceLocations", "failurePath", "status", "findingHash"
  ],
  "properties": {
    "schemaVersion": {"const": 3},
    "planHash": {"$ref": "#/$defs/sha256"},
    "attemptRef": {"$ref": "#/$defs/stableId"},
    "createdAt": {"$ref": "#/$defs/utcTimestamp"},
    "finalDiffHash": {"$ref": "#/$defs/sha256"},
    "diffSignalSetHash": {"$ref": "#/$defs/sha256"},
    "fingerprint": {"$ref": "#/$defs/fingerprint"},
    "severity": {"enum": ["critical", "high", "medium", "low", "info"]},
    "rootCauseOwner": {"enum": ["design", "plan", "implemented", "reviewed", "verified"]},
    "detectionPoint": {"$ref": "#/$defs/stableId"},
    "evidenceLocations": {
      "type": "array", "minItems": 1, "maxItems": 4096, "uniqueItems": true,
      "items": {"$ref": "#/$defs/evidenceLocation"}
    },
    "failurePath": {"type": "array", "minItems": 1, "maxItems": 128, "items": {"$ref": "#/$defs/stableId"}},
    "status": {"enum": ["open", "accepted", "resolved", "false-positive"]},
    "findingHash": {"$ref": "#/$defs/sha256"}
  },
  "$defs": {
    "stableId": {"type": "string", "pattern": "^[a-z0-9][a-z0-9._:-]{0,127}$"},
    "sha256": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"},
    "fingerprint": {"type": "string", "minLength": 1, "maxLength": 256, "pattern": "^[a-z0-9][a-z0-9._:-]{0,255}$"},
    "utcTimestamp": {
      "type": "string", "format": "date-time",
      "pattern": "^\\d{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\\d|3[01])T(?:[01]\\d|2[0-3]):[0-5]\\d:[0-5]\\d(?:\\.\\d+)?Z$"
    },
    "evidenceLocation": {
      "type": "object", "additionalProperties": false,
      "required": ["evidenceRef", "path"],
      "properties": {
        "evidenceRef": {"$ref": "#/$defs/stableId"},
        "path": {"type": "string", "minLength": 1, "pattern": "^[^\\u0000]+$"},
        "line": {"type": "integer", "minimum": 1},
        "column": {"type": "integer", "minimum": 1}
      }
    }
  }
}

````
