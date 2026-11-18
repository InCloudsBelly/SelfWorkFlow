# 只读参考：work-artifact-operation.schema.json

此处为资料或模板，不提供可执行程序；实际工具须独立配置。

````text
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "additionalProperties": false,
  "required": ["schemaVersion", "nonce", "payloadHash", "result", "createdAt"],
  "properties": {
    "schemaVersion": {"const": 1},
    "nonce": {"type": "string", "minLength": 1, "maxLength": 1024},
    "payloadHash": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"},
    "result": {"type": "object"},
    "createdAt": {"type": "string", "minLength": 1}
  }
}

````
