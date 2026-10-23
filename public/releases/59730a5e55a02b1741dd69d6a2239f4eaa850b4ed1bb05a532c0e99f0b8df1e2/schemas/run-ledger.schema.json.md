# 只读参考：run-ledger.schema.json

此处为资料或模板，不提供可执行程序；实际工具须独立配置。

````text
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object", "additionalProperties": false,
  "required": ["schemaVersion", "planHash", "requestHash", "capabilitySnapshotHash", "status", "stages"],
  "properties": {
    "schemaVersion": {"const": 2},
    "planHash": {"$ref": "#/$defs/hash"}, "requestHash": {"$ref": "#/$defs/hash"}, "capabilitySnapshotHash": {"$ref": "#/$defs/hash"},
    "status": {"enum": ["pending", "active", "paused", "failed", "completed", "superseded"]},
    "stages": {"type": "array", "uniqueItems": true, "items": {"$ref": "#/$defs/stage"}, "contains": {"type": "object", "properties": {"status": {"const": "active"}}, "required": ["status"]}, "minContains": 0, "maxContains": 1},
    "supersededByPlanHash": {"$ref": "#/$defs/hash"}
  },
  "allOf": [{"if": {"properties": {"status": {"const": "superseded"}}, "required": ["status"]}, "then": {"required": ["supersededByPlanHash"]}}],
  "$defs": {
    "hash": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"},
    "id": {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"},
    "evidenceRef": {"type": "string", "minLength": 1, "maxLength": 256},
    "attempt": {"type": "object", "additionalProperties": false, "required": ["attemptRef", "ordinal", "previousAttemptRef"], "properties": {"attemptRef": {"$ref": "#/$defs/id"}, "ordinal": {"type": "integer", "minimum": 1, "maximum": 1024}, "previousAttemptRef": {"oneOf": [{"type": "null"}, {"$ref": "#/$defs/id"}]}}},
    "slotResult": {"type": "object", "additionalProperties": false, "required": ["attemptRef", "moduleId", "resultRef"], "properties": {"attemptRef": {"$ref": "#/$defs/id"}, "moduleId": {"$ref": "#/$defs/id"}, "resultRef": {"$ref": "#/$defs/id"}}},
    "gateResult": {"type": "object", "additionalProperties": false, "required": ["attemptRef", "gateId", "outcome", "resultRef"], "properties": {"attemptRef": {"$ref": "#/$defs/id"}, "gateId": {"$ref": "#/$defs/id"}, "outcome": {"enum": ["passed", "failed", "paused"]}, "resultRef": {"$ref": "#/$defs/id"}}},
    "runtimeSkip": {"type": "object", "additionalProperties": false, "required": ["attemptRef", "slotId", "evidenceRef"], "properties": {"attemptRef": {"$ref": "#/$defs/id"}, "slotId": {"$ref": "#/$defs/id"}, "evidenceRef": {"$ref": "#/$defs/evidenceRef"}}},
    "stage": {
      "type": "object", "additionalProperties": false,
      "required": ["stageId", "status", "attempts", "slotResults", "gateResults", "runtimeSkips"],
      "properties": {
        "stageId": {"$ref": "#/$defs/id"}, "status": {"enum": ["pending", "active", "passed", "failed", "paused", "skipped"]},
        "attempts": {"type": "array", "uniqueItems": true, "maxItems": 1024, "items": {"$ref": "#/$defs/attempt"}},
        "slotResults": {"type": "array", "uniqueItems": true, "maxItems": 256, "items": {"$ref": "#/$defs/slotResult"}},
        "gateResults": {"type": "array", "uniqueItems": true, "maxItems": 256, "items": {"$ref": "#/$defs/gateResult"}},
        "runtimeSkips": {"type": "array", "uniqueItems": true, "maxItems": 256, "items": {"$ref": "#/$defs/runtimeSkip"}}
      }
    }
  }
}

````
