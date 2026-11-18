# 只读参考：trusted-command-registry.schema.json

此处为资料或模板，不提供可执行程序；实际工具须独立配置。

````text
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://selfworkflow.local/schemas/v3/trusted-command-registry.schema.json",
  "title": "SelfWorkFlow V3 trusted Provider command registry",
  "type": "object",
  "additionalProperties": false,
  "required": ["schemaVersion", "registryHash", "issuerId", "trustSource", "templates"],
  "properties": {
    "schemaVersion": {"const": 3},
    "registryHash": {"$ref": "#/$defs/hash"},
    "issuerId": {"$ref": "#/$defs/id"},
    "trustSource": {"enum": ["host-attested", "test-fixture"]},
    "templates": {"type": "array", "minItems": 1, "maxItems": 256, "items": {"$ref": "provider-command-template.schema.json"}}
  },
  "$defs": {
    "id": {"type": "string", "pattern": "^[a-z0-9][a-z0-9._-]{0,127}$"},
    "hash": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"}
  }
}

````
