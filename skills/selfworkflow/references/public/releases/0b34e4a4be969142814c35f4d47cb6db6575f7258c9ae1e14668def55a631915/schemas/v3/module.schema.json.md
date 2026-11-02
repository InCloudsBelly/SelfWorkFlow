# 只读参考：module.schema.json

此处为资料或模板，不提供可执行程序；实际工具须独立配置。

````text
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://selfworkflow.local/schemas/v3/module.schema.json",
  "title": "SelfWorkFlow V3 orchestration module",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "schemaVersion",
    "id",
    "sourceHash",
    "stage",
    "slot",
    "selectionMode",
    "invocation",
    "dependencies",
    "conflicts",
    "contextCost",
    "supportEvidence"
  ],
  "properties": {
    "schemaVersion": {"const": 3},
    "id": {"$ref": "#/$defs/stableId"},
    "sourceHash": {"$ref": "#/$defs/sha256"},
    "stage": {
      "enum": [
        "discovered",
        "capability-checked",
        "classified",
        "designed",
        "planned",
        "implemented",
        "reviewed",
        "verified",
        "completed"
      ]
    },
    "slot": {"$ref": "#/$defs/stableId"},
    "selectionMode": {"enum": ["static", "bounded-runtime"]},
    "invocation": {"$ref": "#/$defs/invocation"},
    "dependencies": {"$ref": "#/$defs/stableIdList"},
    "conflicts": {"$ref": "#/$defs/stableIdList"},
    "contextCost": {"$ref": "#/$defs/contextCost"},
    "supportEvidence": {"$ref": "#/$defs/supportEvidence"}
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
    "stableIdList": {
      "type": "array",
      "maxItems": 256,
      "uniqueItems": true,
      "items": {"$ref": "#/$defs/stableId"}
    },
    "invocation": {
      "type": "object",
      "additionalProperties": false,
      "required": ["kind", "ref"],
      "properties": {
        "kind": {"enum": ["agent-native", "skill", "mcp"]},
        "ref": {"type": "string", "minLength": 1, "maxLength": 512}
      }
    },
    "contextCost": {
      "type": "object",
      "additionalProperties": false,
      "required": ["estimatedContextCost", "estimatedExecutionCost"],
      "properties": {
        "estimatedContextCost": {"type": "integer", "minimum": 0, "maximum": 1000000},
        "estimatedExecutionCost": {"type": "integer", "minimum": 0, "maximum": 1000000}
      }
    },
    "supportEvidence": {
      "type": "object",
      "additionalProperties": false,
      "required": ["sourceIntegrity", "adapterSupport", "runtimeCapability", "behaviorEvidence"],
      "properties": {
        "sourceIntegrity": {"enum": ["supported", "unverified", "unsupported"]},
        "adapterSupport": {"enum": ["supported", "unverified", "unsupported"]},
        "runtimeCapability": {"enum": ["supported", "unverified", "unsupported"]},
        "behaviorEvidence": {"enum": ["supported", "unverified", "unsupported"]}
      }
    }
  }
}

````
