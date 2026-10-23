# 只读参考：provider-binding-snapshot.schema.json

此处为资料或模板，不提供可执行程序；实际工具须独立配置。

````text
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://selfworkflow.local/schemas/v3/provider-binding-snapshot.schema.json",
  "title": "SelfWorkFlow V3 static provider binding snapshot",
  "type": "object", "additionalProperties": false,
  "required": ["schemaVersion", "bindingSnapshotHash", "bindings"],
  "properties": {"schemaVersion": {"const": 3}, "bindingSnapshotHash": {"$ref": "#/$defs/hash"}, "bindings": {"type": "array", "maxItems": 4096, "items": {"$ref": "#/$defs/binding"}}},
  "$defs": {
    "id": {"type": "string", "pattern": "^[a-z0-9][a-z0-9._-]{0,127}$"},
    "hash": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"},
    "layer": {"enum": ["task-explicit", "project", "user-machine", "pinned-public", "reportable-builtin"]},
    "binding": {
      "type": "object", "additionalProperties": false,
      "required": ["bindingHash", "moduleId", "providerId", "capabilityId", "operationId", "platform", "configurationLayer", "adapterHash", "sourceIdentityHash", "supportMatrixHash", "supportMatrixEntryRef", "supportMatrixEntryHash", "requirementMode"],
      "properties": {
        "bindingHash": {"$ref": "#/$defs/hash"}, "moduleId": {"$ref": "#/$defs/id"},
        "providerId": {"$ref": "#/$defs/id"}, "capabilityId": {"$ref": "#/$defs/id"},
        "operationId": {"$ref": "#/$defs/id"}, "platform": {"type": "string", "pattern": "^[a-z0-9][a-z0-9._-]{0,63}$"},
        "configurationLayer": {"$ref": "#/$defs/layer"},
        "adapterHash": {"$ref": "#/$defs/hash"}, "sourceIdentityHash": {"$ref": "#/$defs/hash"},
        "supportMatrixHash": {"$ref": "#/$defs/hash"}, "supportMatrixEntryRef": {"$ref": "#/$defs/id"},
        "supportMatrixEntryHash": {"$ref": "#/$defs/hash"}, "requirementMode": {"enum": ["required", "preferred"]}
      }
    }
  }
}

````
