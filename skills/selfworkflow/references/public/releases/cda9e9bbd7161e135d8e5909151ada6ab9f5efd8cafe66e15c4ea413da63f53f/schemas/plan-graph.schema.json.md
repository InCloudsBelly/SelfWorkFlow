# 只读参考：plan-graph.schema.json

此处为资料或模板，不提供可执行程序；实际工具须独立配置。

````text
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object", "additionalProperties": false,
  "required": ["schemaVersion", "requestHash", "capabilitySnapshotHash", "pipelineHash", "policyHash", "catalogHash", "planHash", "strength", "stages"],
  "properties": {
    "schemaVersion": {"const": 2},
    "requestHash": {"$ref": "#/$defs/hash"},
    "capabilitySnapshotHash": {"$ref": "#/$defs/hash"},
    "pipelineHash": {"$ref": "#/$defs/hash"},
    "policyHash": {"$ref": "#/$defs/hash"},
    "catalogHash": {"$ref": "#/$defs/hash"},
    "planHash": {"$ref": "#/$defs/hash"},
    "strength": {"enum": ["Light", "Full", "Deep"]},
    "stages": {"type": "array", "maxItems": 32, "items": {"$ref": "#/$defs/stage"}}
  },
  "$defs": {
    "hash": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"},
    "id": {"type": "string", "pattern": "^[a-z][a-z0-9.-]{0,127}$"},
    "stage": {"type": "object", "additionalProperties": false, "required": ["stageId", "failureOwner", "applicability", "slots"], "properties": {"stageId": {"$ref": "#/$defs/id"}, "failureOwner": {"$ref": "#/$defs/id"}, "applicability": {"enum": ["applicable", "not-applicable", "blocked"]}, "slots": {"type": "array", "maxItems": 64, "items": {"$ref": "#/$defs/slot"}}}},
    "slot": {"type": "object", "additionalProperties": false, "required": ["slotId", "cardinality", "applicability", "selectedModules", "gates"], "properties": {"slotId": {"$ref": "#/$defs/id"}, "cardinality": {"enum": ["exactly-one", "zero-or-one", "zero-or-many", "gate"]}, "applicability": {"enum": ["applicable", "not-applicable", "blocked"]}, "selectedModules": {"type": "array", "uniqueItems": true, "items": {"$ref": "#/$defs/id"}}, "gates": {"type": "array", "uniqueItems": true, "items": {"$ref": "#/$defs/id"}}}}
  }
}

````
