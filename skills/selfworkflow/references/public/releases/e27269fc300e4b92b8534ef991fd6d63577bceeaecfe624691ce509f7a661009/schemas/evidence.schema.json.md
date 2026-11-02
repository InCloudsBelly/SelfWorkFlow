# 只读参考：evidence.schema.json

此处为资料或模板，不提供可执行程序；实际工具须独立配置。

````text
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://selfworkflow.local/schemas/evidence.schema.json",
  "title": "SelfWorkFlow evidence configuration",
  "type": "object",
  "additionalProperties": false,
  "required": ["schemaVersion", "requiredFields", "verification"],
  "properties": {
    "schemaVersion": {"const": 1},
    "requiredFields": {
      "type": "array",
      "prefixItems": [
        {"const": "classification"},
        {"const": "capabilities"},
        {"const": "selectedSkills"},
        {"const": "acceptanceCriteria"},
        {"const": "changes"},
        {"const": "review"},
        {"const": "verification"},
        {"const": "skipped"},
        {"const": "residualRisks"}
      ],
      "items": false,
      "minItems": 9
    },
    "verification": {
      "type": "object",
      "additionalProperties": false,
      "required": ["unverifiedFrom", "completionEligible"],
      "properties": {
        "unverifiedFrom": {
          "type": "array",
          "prefixItems": [
            {"const": "not-run"},
            {"const": "partial"}
          ],
          "items": false,
          "minItems": 2
        },
        "completionEligible": {
          "type": "array",
          "prefixItems": [
            {"const": "passed"},
            {"const": "not-applicable"}
          ],
          "items": false,
          "minItems": 2
        }
      }
    }
  }
}

````
