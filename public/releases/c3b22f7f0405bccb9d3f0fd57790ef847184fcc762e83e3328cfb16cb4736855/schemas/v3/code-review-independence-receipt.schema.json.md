# 只读参考：code-review-independence-receipt.schema.json

此处为资料或模板，不提供可执行程序；实际工具须独立配置。

````text
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://selfworkflow.local/schemas/v3/code-review-independence-receipt.schema.json",
  "title": "SelfWorkFlow V3 code review independence receipt",
  "type": "object", "additionalProperties": false,
  "required": ["schemaVersion", "reviewMode", "dispatchId", "dispatchNonce", "planHash", "attemptRef", "issuedAt", "expiresAt", "forkContext", "implementationAgentIdentity", "implementationContextIdentity", "reviewerAgentIdentity", "reviewerContextIdentity", "hostAgentIdentity", "hostContextIdentity", "hostAttestationRef", "inputMode", "parentContextImported", "grillReasoningReceived", "payloadHash", "reviewSubjectHash", "reviewerPolicyHash", "resultHash", "reviewVerdict", "reviewLevel", "fallbackAuthorizationRef", "independence", "reviewExecutionMode", "subagentLifecycle", "subagentExecutionId", "reviewModel", "skillManifestHash", "reviewPackageHash", "reviewReportMarkdown", "reviewReportHash", "receiptHash"],
  "properties": {
    "schemaVersion": {"const": 3},
    "reviewMode": {"const": "independent-code-review"},
    "dispatchId": {"$ref": "#/$defs/id"},
    "dispatchNonce": {"$ref": "#/$defs/id"},
    "planHash": {"$ref": "#/$defs/hash"},
    "attemptRef": {"$ref": "#/$defs/id"},
    "issuedAt": {"type": "string", "format": "utc-date-time"},
    "expiresAt": {"type": "string", "format": "utc-date-time"},
    "forkContext": {"const": false},
    "implementationAgentIdentity": {"$ref": "#/$defs/id"},
    "implementationContextIdentity": {"$ref": "#/$defs/id"},
    "reviewerAgentIdentity": {"$ref": "#/$defs/id"},
    "reviewerContextIdentity": {"$ref": "#/$defs/id"},
    "subagentExecutionId": {"$ref": "#/$defs/id"},
    "hostAgentIdentity": {"$ref": "#/$defs/id"},
    "hostContextIdentity": {"$ref": "#/$defs/id"},
    "hostAttestationRef": {"oneOf": [{"$ref": "#/$defs/hash"}, {"type": "null"}]},
    "inputMode": {"const": "code-review-subject-only"},
    "parentContextImported": {"const": false},
    "grillReasoningReceived": {"const": false},
    "payloadHash": {"$ref": "#/$defs/hash"},
    "reviewSubjectHash": {"$ref": "#/$defs/hash"},
    "reviewerPolicyHash": {"$ref": "#/$defs/hash"},
    "resultHash": {"$ref": "#/$defs/hash"},
    "reviewVerdict": {"enum": ["approve", "changes-required"]},
    "reviewLevel": {"enum": ["L2", "L3"]},
    "fallbackAuthorizationRef": {"const": null},
    "independence": {"enum": ["independent", "unverified"]},
    "reviewModel": {"oneOf": [{"type": "null"}, {"type": "object", "additionalProperties": false, "required": ["agentId", "model", "reasoningEffort", "selectionMode"], "properties": {"agentId": {"$ref": "#/$defs/id"}, "model": {"type": "string", "minLength": 1, "maxLength": 256}, "reasoningEffort": {"enum": ["low", "medium", "high", "xhigh", "max", "ultra"]}, "selectionMode": {"enum": ["default", "one-time"]}}}]},
    "skillManifestHash": {"$ref": "#/$defs/hash"},
    "reviewPackageHash": {"oneOf": [{"$ref": "#/$defs/hash"}, {"type": "null"}]},
    "reviewExecutionMode": {"const": "ephemeral-subagent"},
    "subagentLifecycle": {"const": "created-executed-cleaned"},
    "reviewReportMarkdown": {"type": "string", "minLength": 1, "maxLength": 65536},
    "reviewReportHash": {"$ref": "#/$defs/hash"},
    "receiptHash": {"$ref": "#/$defs/hash"}
  },
  "$defs": {
    "id": {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$"},
    "hash": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"}
  }
}

````
