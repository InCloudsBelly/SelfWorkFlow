# 只读参考：resolve-result.schema.json

此处为资料或模板，不提供可执行程序；实际工具须独立配置。

````text
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://selfworkflow.local/schemas/v3/resolve-result.schema.json",
  "title": "SelfWorkFlow V3 resolve result",
  "type": "object",
  "additionalProperties": false,
  "required": ["schemaVersion", "status", "reasonCodes", "diagnostics", "planGraph"],
  "properties": {
    "schemaVersion": {"const": 3},
    "status": {"enum": ["active", "paused"]},
    "reasonCodes": {
      "type": "array",
      "maxItems": 256,
      "uniqueItems": true,
      "items": {"$ref": "#/$defs/stableId"}
    },
    "diagnostics": {
      "type": "array",
      "maxItems": 256,
      "items": {"$ref": "#/$defs/diagnostic"}
    },
    "planGraph": {
      "oneOf": [
        {"type": "null"},
        {"$ref": "https://selfworkflow.local/schemas/v3/plan-graph.schema.json"}
      ]
    },
    "capabilityRoute": {
      "$ref": "https://selfworkflow.local/schemas/v3/capability-route.schema.json"
    },
    "ponytailRoute": {
      "$ref": "https://selfworkflow.local/schemas/v3/ponytail-route.schema.json"
    }
  },
  "allOf": [
    {
      "if": {"properties": {"status": {"const": "paused"}}, "required": ["status"]},
      "then": {
        "properties": {"reasonCodes": {"minItems": 1}}
      }
    }
  ],
  "$defs": {
    "stableId": {
      "type": "string",
      "pattern": "^[a-z0-9][a-z0-9._-]{0,127}$"
    },
    "diagnostic": {
      "type": "object",
      "additionalProperties": false,
      "required": ["code", "severity"],
      "properties": {
        "code": {"$ref": "#/$defs/stableId"},
        "severity": {"enum": ["info", "warning", "error"]},
        "message": {"type": "string", "minLength": 1, "maxLength": 4096}
      }
    }
  }
}

````
