# 只读参考：catalog.schema.json

此处为资料或模板，不提供可执行程序；实际工具须独立配置。

````text
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://selfworkflow.local/schemas/v3/catalog.schema.json",
  "title": "SelfWorkFlow V3 orchestration catalog",
  "type": "object",
  "additionalProperties": false,
  "required": ["schemaVersion", "catalogHash", "domains", "modules"],
  "properties": {
    "schemaVersion": {"const": 3},
    "catalogHash": {"$ref": "#/$defs/sha256"},
    "domains": {
      "type": "array",
      "maxItems": 128,
      "uniqueItems": true,
      "items": {"$ref": "#/$defs/domainRef"}
    },
    "modules": {
      "type": "array",
      "maxItems": 4096,
      "items": {
        "oneOf": [
          {"$ref": "https://selfworkflow.local/schemas/v3/module.schema.json"},
          {"$ref": "#/$defs/moduleRef"}
        ]
      }
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
    "moduleRef": {
      "type": "object",
      "additionalProperties": false,
      "required": ["id", "ref", "hash"],
      "properties": {
        "id": {"$ref": "#/$defs/stableId"},
        "ref": {"type": "string", "minLength": 1, "maxLength": 1024},
        "hash": {"$ref": "#/$defs/sha256"}
      }
    },
    "domainRef": {
      "type": "object",
      "additionalProperties": false,
      "required": ["id", "ref", "hash"],
      "properties": {
        "id": {"$ref": "#/$defs/stableId"},
        "ref": {"type": "string", "minLength": 1, "maxLength": 1024},
        "hash": {"$ref": "#/$defs/sha256"}
      }
    }
  }
}

````
