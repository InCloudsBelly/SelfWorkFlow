"""Constructor-bound trust bundle for post-Grill Host integration."""

from __future__ import annotations

from typing import Any, Callable

from selfworkflow.v3.hashing import content_hash
from selfworkflow.v3.review_policy import ReviewPolicyArtifact


class ReviewServiceError(ValueError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


_SERVICE_TOKEN = object()


class ReviewHostServices:
    """Sealed ports selected by the embedding Host, never by Agent input."""

    __slots__ = (
        "dispatch_port", "summary_resolver", "summary_attestation_resolver",
        "grill_completion_resolver", "review_policy_hash", "host_attestation_resolver",
        "host_attestation_consumer", "fallback_authorization_resolver",
        "fallback_authorization_consumer", "backend_class", "_token",
        "independent_context_available",
        "review_execution_mode",
    )

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("ReviewHostServices is issued by bind_review_host_services")

    def __setattr__(self, _name: str, _value: object) -> None:
        raise AttributeError("ReviewHostServices is immutable")

    def _is_valid(self, *, test_mode: bool) -> bool:
        return (
            self._token is _SERVICE_TOKEN
            and self.backend_class in {"external-host", "fake-test"}
            and (test_mode or self.backend_class == "external-host")
        )


def bind_review_host_services(
    *,
    dispatch_port: object,
    summary_resolver: Callable[[str], object],
    summary_attestation_resolver: Callable[[str], object],
    grill_completion_resolver: Callable[[str], object],
    host_attestation_resolver: Callable[[str], object],
    host_attestation_consumer: Callable[[str, str], bool],
    fallback_authorization_resolver: Callable[[str], object],
    fallback_authorization_consumer: Callable[[str, str], bool],
    review_policy: ReviewPolicyArtifact,
    service_attestation: dict[str, Any],
    test_mode: bool = False,
) -> ReviewHostServices:
    """Bind one immutable service set after validating its Host attestation."""

    required = {
        "schemaVersion", "backendClass", "dispatchPortBound",
        "artifactResolversBound", "replayConsumersBound", "reviewPolicyHash",
        "independentContextAvailable", "reviewExecutionMode", "attestationHash",
    }
    if type(service_attestation) is not dict or set(service_attestation) != required:
        raise ReviewServiceError("review-host-service-attestation-invalid")
    if (
        service_attestation["schemaVersion"] != 3
        or service_attestation["backendClass"] not in {"external-host", "fake-test"}
        or service_attestation["dispatchPortBound"] is not True
        or service_attestation["artifactResolversBound"] is not True
        or service_attestation["replayConsumersBound"] is not True
        or type(service_attestation["independentContextAvailable"]) is not bool
        or service_attestation["reviewExecutionMode"] != "ephemeral-subagent"
        or type(review_policy) is not ReviewPolicyArtifact
        or not review_policy._is_valid()
        or service_attestation["reviewPolicyHash"] != review_policy.policy_hash
        or service_attestation["attestationHash"] != content_hash({
            key: value for key, value in service_attestation.items()
            if key != "attestationHash"
        })
        or (not test_mode and service_attestation["backendClass"] != "external-host")
        or not hasattr(dispatch_port, "dispatch_review")
        or not all(callable(item) for item in (
            summary_resolver, summary_attestation_resolver,
            grill_completion_resolver, host_attestation_resolver,
            host_attestation_consumer, fallback_authorization_resolver,
            fallback_authorization_consumer,
        ))
    ):
        raise ReviewServiceError("review-host-service-attestation-invalid")
    services = object.__new__(ReviewHostServices)
    object.__setattr__(services, "dispatch_port", dispatch_port)
    object.__setattr__(services, "summary_resolver", summary_resolver)
    object.__setattr__(services, "summary_attestation_resolver", summary_attestation_resolver)
    object.__setattr__(services, "grill_completion_resolver", grill_completion_resolver)
    object.__setattr__(services, "review_policy_hash", review_policy.policy_hash)
    object.__setattr__(services, "host_attestation_resolver", host_attestation_resolver)
    object.__setattr__(services, "host_attestation_consumer", host_attestation_consumer)
    object.__setattr__(services, "fallback_authorization_resolver", fallback_authorization_resolver)
    object.__setattr__(services, "fallback_authorization_consumer", fallback_authorization_consumer)
    object.__setattr__(services, "backend_class", service_attestation["backendClass"])
    object.__setattr__(
        services, "independent_context_available",
        service_attestation["independentContextAvailable"],
    )
    object.__setattr__(
        services, "review_execution_mode", service_attestation["reviewExecutionMode"],
    )
    object.__setattr__(services, "_token", _SERVICE_TOKEN)
    return services
