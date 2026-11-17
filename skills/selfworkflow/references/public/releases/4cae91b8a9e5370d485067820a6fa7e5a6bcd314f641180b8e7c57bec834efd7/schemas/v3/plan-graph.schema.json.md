# 只读参考：plan-graph.schema.json

此处为资料或模板，不提供可执行程序；实际工具须独立配置。

````text
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://selfworkflow.local/schemas/v3/plan-graph.schema.json",
  "title": "SelfWorkFlow V3 immutable execution plan graph",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "schemaVersion", "planHash", "requestHash", "capabilitySnapshotHash",
    "pipelineHash", "policyHash", "catalogHash", "providerPreferenceHash",
    "providerBindingHash", "executionPolicyHash", "moduleConstraints", "stages"
  ],
  "properties": {
    "schemaVersion": {"const": 3},
    "planHash": {"$ref": "#/$defs/sha256"},
    "requestHash": {"$ref": "#/$defs/sha256"},
    "capabilitySnapshotHash": {"$ref": "#/$defs/sha256"},
    "pipelineHash": {"$ref": "#/$defs/sha256"},
    "policyHash": {"$ref": "#/$defs/sha256"},
    "catalogHash": {"$ref": "#/$defs/sha256"},
    "providerPreferenceHash": {"$ref": "#/$defs/sha256"},
    "providerBindingHash": {"$ref": "#/$defs/sha256"},
    "executionPolicyHash": {"$ref": "#/$defs/sha256"},
    "moduleConstraints": {
      "type": "array",
      "maxItems": 4096,
      "items": {"$ref": "#/$defs/moduleConstraint"}
    },
    "stages": {
      "type": "array",
      "minItems": 1,
      "maxItems": 128,
      "items": {"$ref": "#/$defs/stage"}
    }
  },
  "$defs": {
    "stableId": {
      "type": "string",
      "pattern": "^[a-z0-9][a-z0-9._-]{0,127}$"
    },
    "sha256": {
      "type": "string",
      "pattern": "^sha256:[0-9a-f]{64}$"
    },
    "idList": {
      "type": "array",
      "maxItems": 4096,
      "uniqueItems": true,
      "items": {"$ref": "#/$defs/stableId"}
    },
    "applicability": {
      "enum": ["applicable", "not-applicable", "blocked"]
    },
    "moduleConstraint": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "moduleId", "stageId", "slotId", "dependencies", "conflicts",
        "estimatedContextCost", "estimatedExecutionCost"
      ],
      "properties": {
        "moduleId": {"$ref": "#/$defs/stableId"},
        "stageId": {"$ref": "#/$defs/stableId"},
        "slotId": {"$ref": "#/$defs/stableId"},
        "dependencies": {"$ref": "#/$defs/idList"},
        "conflicts": {"$ref": "#/$defs/idList"},
        "estimatedContextCost": {"type": "integer", "minimum": 0, "maximum": 1000000},
        "estimatedExecutionCost": {"type": "integer", "minimum": 0, "maximum": 1000000}
      }
    },
    "stage": {
      "type": "object",
      "additionalProperties": false,
      "required": ["stageId", "ordinal", "applicability", "slots"],
      "properties": {
        "stageId": {"$ref": "#/$defs/stableId"},
        "ordinal": {"type": "integer", "minimum": 1, "maximum": 128},
        "applicability": {"$ref": "#/$defs/applicability"},
        "slots": {
          "type": "array",
          "minItems": 1,
          "maxItems": 128,
          "items": {"$ref": "#/$defs/slot"}
        }
      }
    },
    "slot": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "slotId", "ordinal", "cardinality", "selectionMode", "selectedModules",
        "eligibleModules", "selectionPolicyRef", "selectionPolicyHash",
        "coverageObligations", "gates", "applicability"
      ],
      "properties": {
        "slotId": {"$ref": "#/$defs/stableId"},
        "ordinal": {"type": "integer", "minimum": 1, "maximum": 128},
        "cardinality": {"enum": ["exactly-one", "zero-or-one", "zero-or-many", "gate"]},
        "selectionMode": {"enum": ["static", "bounded-runtime"]},
        "selectedModules": {"$ref": "#/$defs/idList"},
        "eligibleModules": {"$ref": "#/$defs/idList"},
        "selectionPolicyRef": {"$ref": "#/$defs/stableId"},
        "selectionPolicyHash": {"$ref": "#/$defs/sha256"},
        "coverageObligations": {"$ref": "#/$defs/idList"},
        "gates": {"$ref": "#/$defs/idList"},
        "applicability": {"$ref": "#/$defs/applicability"}
      }
    }
  }
}

````
