# 只读参考：resolve-result.schema.json

此处为资料或模板，不提供可执行程序；实际工具须独立配置。

````text
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object", "additionalProperties": false,
  "required": ["schemaVersion", "status", "reasonCodes", "diagnostics", "planGraph"],
  "properties": {
    "schemaVersion": {"const": 2}, "status": {"enum": ["active", "paused"]},
    "reasonCodes": {"type": "array", "uniqueItems": true, "items": {"type": "string", "pattern": "^[a-z][a-z0-9.-]{0,127}$"}},
    "diagnostics": {"type": "array", "maxItems": 256, "items": {"type": "object", "additionalProperties": false, "required": ["code", "severity"], "properties": {"code": {"type": "string", "pattern": "^[a-z][a-z0-9.-]{0,127}$"}, "severity": {"enum": ["info", "warning", "error"]}}}},
    "planGraph": {"type": "object"}
  }
}

````
