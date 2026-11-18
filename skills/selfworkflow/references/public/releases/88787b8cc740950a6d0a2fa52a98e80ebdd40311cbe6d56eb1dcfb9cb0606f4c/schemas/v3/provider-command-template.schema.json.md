# 只读参考：provider-command-template.schema.json

此处为资料或模板，不提供可执行程序；实际工具须独立配置。

````text
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://selfworkflow.local/schemas/v3/provider-command-template.schema.json",
  "title": "SelfWorkFlow V3 trusted Provider command template",
  "type": "object",
  "additionalProperties": false,
  "required": ["schemaVersion", "templateHash", "templateId", "providerId", "bindingSnapshotHash", "adapterHash", "operationId", "sideEffectClass", "executable", "argvTemplate", "parameterNames", "envAllowlist", "cwdPolicy"],
  "properties": {
    "schemaVersion": {"const": 3},
    "templateHash": {"$ref": "#/$defs/hash"},
    "templateId": {"$ref": "#/$defs/id"},
    "providerId": {"$ref": "#/$defs/id"},
    "bindingSnapshotHash": {"$ref": "#/$defs/hash"},
    "adapterHash": {"$ref": "#/$defs/hash"},
    "operationId": {"$ref": "#/$defs/id"},
    "sideEffectClass": {"enum": ["none", "local-write"]},
    "executable": {"type": "string", "minLength": 1, "maxLength": 32767},
    "argvTemplate": {"type": "array", "minItems": 1, "maxItems": 256, "items": {"type": "string", "minLength": 1, "maxLength": 4096}},
    "parameterNames": {"type": "array", "maxItems": 64, "uniqueItems": true, "items": {"$ref": "#/$defs/id"}},
    "envAllowlist": {"type": "array", "maxItems": 64, "uniqueItems": true, "items": {"type": "string", "pattern": "^[A-Z][A-Z0-9_]{0,127}$"}},
    "cwdPolicy": {"const": "project-root"}
  },
  "$defs": {
    "id": {"type": "string", "pattern": "^[a-z0-9][a-z0-9._-]{0,127}$"},
    "hash": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"}
  }
}

````
