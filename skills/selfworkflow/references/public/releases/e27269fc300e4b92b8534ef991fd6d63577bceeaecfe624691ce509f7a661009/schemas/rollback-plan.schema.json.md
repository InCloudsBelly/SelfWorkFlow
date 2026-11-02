# 只读参考：rollback-plan.schema.json

此处为资料或模板，不提供可执行程序；实际工具须独立配置。

````text
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "additionalProperties": false,
  "required": ["schemaVersion", "operation", "transactionId", "transactionPath", "transactionHash", "stateRoot", "targetVersion", "operations", "securityStatus", "planHash"],
  "properties": {
    "schemaVersion": {"const": 1}, "operation": {"const": "rollback"},
    "transactionId": {"type": "string"}, "transactionPath": {"type": "string"},
    "transactionHash": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"},
    "stateRoot": {"type": "string"}, "targetVersion": {"type": "string"},
    "operations": {
      "type": "array",
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["target", "expectedHash", "beforeExists", "beforeHash", "backupPath"],
        "properties": {
          "target": {"type": "string"},
          "expectedHash": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"},
          "beforeExists": {"type": "boolean"},
          "beforeHash": {"type": ["string", "null"]},
          "backupPath": {"type": ["string", "null"]}
        }
      }
    },
    "securityStatus": {"enum": ["verified", "unverified"]},
    "planHash": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"}
  }
}

````
