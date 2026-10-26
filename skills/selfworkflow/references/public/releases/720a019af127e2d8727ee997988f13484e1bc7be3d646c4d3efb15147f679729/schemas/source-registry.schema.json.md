# 只读参考：source-registry.schema.json

此处为资料或模板，不提供可执行程序；实际工具须独立配置。

````text
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "additionalProperties": false,
  "required": ["schemaVersion", "sources"],
  "properties": {
    "schemaVersion": {"const": 1},
    "sources": {
      "type": "array",
      "minItems": 1,
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["id", "sourceType", "revision", "repositoryDirty", "selectedFilesDirty", "supportStatus"],
        "properties": {
          "id": {"type": "string", "pattern": "^[a-z0-9][a-z0-9._-]{0,127}$"},
          "sourceType": {"enum": ["local-git-reference", "git-url-reference"]},
          "revision": {"type": "string", "pattern": "^[0-9a-f]{40}$"},
          "repositoryDirty": {"type": "boolean"},
          "selectedFilesDirty": {"type": "boolean"},
          "supportStatus": {"enum": ["reference-only", "candidate", "published"]}
        }
      }
    }
  }
}

````
