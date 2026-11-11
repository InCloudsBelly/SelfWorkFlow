# 只读参考：git-policy.schema.json

此处为资料或模板，不提供可执行程序；实际工具须独立配置。

````text
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object", "additionalProperties": false,
  "required": ["schemaVersion", "forbiddenRoots", "allowedSensitiveNames", "databaseSuffixes", "sizeBytes", "allowlist"],
  "properties": {
    "schemaVersion": {"const": 1},
    "forbiddenRoots": {"$ref": "#/$defs/strings"}, "allowedSensitiveNames": {"$ref": "#/$defs/strings"}, "databaseSuffixes": {"$ref": "#/$defs/strings"},
    "sizeBytes": {"type": "object", "additionalProperties": false, "required": ["warning", "failure"], "properties": {"warning": {"type": "integer", "minimum": 1}, "failure": {"type": "integer", "minimum": 2}}},
    "allowlist": {"type": "array", "maxItems": 256, "items": {"type": "object", "additionalProperties": false, "required": ["path", "objectHash", "reason", "owner", "expires"], "properties": {"path": {"type": "string", "minLength": 1, "maxLength": 1024}, "objectHash": {"type": "string", "pattern": "^[0-9a-f]{40,64}$"}, "reason": {"type": "string", "minLength": 1, "maxLength": 512}, "owner": {"type": "string", "minLength": 1, "maxLength": 256}, "expires": {"type": "string", "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}$"}}}}
  },
  "$defs": {"strings": {"type": "array", "maxItems": 256, "uniqueItems": true, "items": {"type": "string", "minLength": 1, "maxLength": 128}}}
}

````
