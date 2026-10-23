# 只读参考：review-host-attestation.schema.json

此处为资料或模板，不提供可执行程序；实际工具须独立配置。

````text
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://selfworkflow.local/schemas/v3/review-host-attestation.schema.json",
  "title": "SelfWorkFlow V3 host-observed review dispatch attestation",
  "type": "object",
  "additionalProperties": false,
  "required": ["schemaVersion", "dispatchId", "dispatchNonce", "planHash", "attemptRef", "issuedAt", "expiresAt", "reviewMode", "forkContext", "payloadHash", "implementationAgentIdentity", "implementationContextIdentity", "hostAgentIdentity", "hostContextIdentity", "reviewerAgentIdentity", "reviewerContextIdentity", "resultHash", "reviewModel", "reviewExecutionMode", "subagentLifecycle", "subagentExecutionId", "reviewReportHash", "skillManifestHash", "reviewPackageHash", "attestationHash"],
  "properties": {
    "schemaVersion": {"const": 3},
    "dispatchId": {"$ref": "#/$defs/id"},
    "dispatchNonce": {"$ref": "#/$defs/id"},
    "planHash": {"$ref": "#/$defs/hash"},
    "attemptRef": {"$ref": "#/$defs/id"},
    "issuedAt": {"type": "string", "format": "utc-date-time"},
    "expiresAt": {"type": "string", "format": "utc-date-time"},
    "reviewMode": {"enum": ["independent-design-review", "independent-code-review"]},
    "forkContext": {"type": "boolean"},
    "payloadHash": {"$ref": "#/$defs/hash"},
    "implementationAgentIdentity": {"$ref": "#/$defs/id"},
    "implementationContextIdentity": {"$ref": "#/$defs/id"},
    "hostAgentIdentity": {"$ref": "#/$defs/id"},
    "hostContextIdentity": {"$ref": "#/$defs/id"},
    "reviewerAgentIdentity": {"$ref": "#/$defs/id"},
    "reviewerContextIdentity": {"$ref": "#/$defs/id"},
    "resultHash": {"$ref": "#/$defs/hash"},
    "reviewModel": {"oneOf": [{"type": "null"}, {"type": "object", "additionalProperties": false, "required": ["agentId", "model", "reasoningEffort", "selectionMode"], "properties": {"agentId": {"$ref": "#/$defs/id"}, "model": {"type": "string", "minLength": 1, "maxLength": 256}, "reasoningEffort": {"enum": ["low", "medium", "high", "xhigh", "max", "ultra"]}, "selectionMode": {"enum": ["default", "one-time"]}}}]},
    "reviewExecutionMode": {"const": "ephemeral-subagent"},
    "subagentLifecycle": {"const": "created-executed-cleaned"},
    "subagentExecutionId": {"$ref": "#/$defs/id"},
    "reviewReportHash": {"$ref": "#/$defs/hash"},
    "skillManifestHash": {"$ref": "#/$defs/hash"},
    "reviewPackageHash": {"oneOf": [{"$ref": "#/$defs/hash"}, {"type": "null"}]},
    "attestationHash": {"$ref": "#/$defs/hash"}
  },
  "$defs": {
    "id": {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$"},
    "hash": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"}
  }
}

````
