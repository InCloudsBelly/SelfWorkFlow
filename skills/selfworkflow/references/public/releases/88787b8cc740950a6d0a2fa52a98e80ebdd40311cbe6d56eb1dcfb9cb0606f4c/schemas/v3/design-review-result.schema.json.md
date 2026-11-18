# 只读参考：design-review-result.schema.json

此处为资料或模板，不提供可执行程序；实际工具须独立配置。

````text
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://selfworkflow.local/schemas/v3/design-review-result.schema.json",
  "title": "SelfWorkFlow V3 structured design review result",
  "type": "object",
  "additionalProperties": false,
  "required": ["schemaVersion", "verdict", "reviewLevel", "summaryHash", "designHash", "findings", "resultHash"],
  "properties": {
    "schemaVersion": {"const": 3},
    "verdict": {"enum": ["approve", "changes-required"]},
    "reviewLevel": {"enum": ["L2", "L3"]},
    "summaryHash": {"$ref": "#/$defs/hash"},
    "designHash": {"$ref": "#/$defs/hash"},
    "findings": {
      "type": "array",
      "maxItems": 256,
      "uniqueItems": true,
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["findingId", "severity", "summary"],
        "properties": {
          "findingId": {"$ref": "#/$defs/id"},
          "severity": {"enum": ["critical", "important", "minor"]},
          "summary": {"type": "string", "minLength": 1, "maxLength": 4096}
        }
      }
    },
    "resultHash": {"$ref": "#/$defs/hash"}
  },
  "$defs": {
    "id": {"type": "string", "pattern": "^[a-z0-9][a-z0-9._-]{0,127}$"},
    "hash": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"}
  }
}

````
