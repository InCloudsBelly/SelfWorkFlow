"""Load and verify a project's explicitly declared Review Skills."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path, PureWindowsPath
import unicodedata
from collections.abc import Mapping
from typing import Any
from types import MappingProxyType

from selfworkflow.config import ConfigError, load_config_bytes
from selfworkflow.v3.catalog import CatalogError, _read_bytes


MAX_PROFILE_BYTES = 64 * 1024
MAX_SKILL_BYTES = 8 * 1024 * 1024
_REPARSE_POINT = 0x400
_CONTEXT_TOKEN = object()
_PROFILE_TOKEN = object()


class ProjectReviewProfileError(ValueError):
    """Stable, redacted failure for an invalid project Review profile."""

    def __init__(self) -> None:
        super().__init__("project-review-profile-invalid")


class ProjectReviewContext(Mapping[str, object]):
    """Host-issued immutable context for the paired code Review inputs."""

    __slots__ = ("_document", "__token")

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("ProjectReviewContext is issued by SelfWorkFlow")

    def __setattr__(self, _name: str, _value: object) -> None:
        raise AttributeError("ProjectReviewContext is immutable")

    def __getitem__(self, key: str) -> object:
        return self._document[key]

    def __iter__(self):
        return iter(self._document)

    def __len__(self) -> int:
        return len(self._document)

    def _is_valid(self) -> bool:
        return (
            getattr(self, "_ProjectReviewContext__token", None) is _CONTEXT_TOKEN
            and isinstance(getattr(self, "_document", None), MappingProxyType)
        )

@dataclass(frozen=True)
class ProjectReviewSkill:
    id: str
    path: str
    content_hash: str
    required: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "path": self.path,
            "contentHash": self.content_hash,
            "required": self.required,
        }


@dataclass(frozen=True)
class ProjectReviewProfile:
    status: str
    project_root: str
    profile_path: str | None
    profile_hash: str | None
    schema_hash: str | None
    binding_hash: str | None
    skills: tuple[ProjectReviewSkill, ...]
    issues: tuple[str, ...]
    blocking: bool
    _profile_token: object = field(default=None, repr=False, compare=False)
    _project_identity: tuple[int, int] | None = field(default=None, repr=False, compare=False)
    _observed_skill_hashes: tuple[str | None, ...] = field(default=(), repr=False, compare=False)
    _verified_contents: tuple[bytes | None, ...] = field(default=(), repr=False, compare=False)

    def _is_valid(self) -> bool:
        return getattr(self, "_profile_token", None) is _PROFILE_TOKEN

    def reviewer_manifest(self) -> tuple[Mapping[str, object], ...]:
        """Return the identical ordered manifest for both Review axes."""

        verified = self._verified_skill_pairs()
        return tuple(
            MappingProxyType(skill.as_dict()) for skill, _content in verified
        )

    def reviewer_manifests(self) -> Mapping[str, tuple[Mapping[str, object], ...]]:
        """Return the same immutable manifest for Standards and Spec."""

        manifest = self.reviewer_manifest()
        return MappingProxyType({"standards": manifest, "spec": manifest})

    def reviewer_skill_bytes(self) -> Mapping[str, tuple[bytes, ...]]:
        """Return the same hash-verified immutable bytes for both Review axes."""

        contents = tuple(content for _skill, content in self._verified_skill_pairs())
        return MappingProxyType({"standards": contents, "spec": contents})

    def _verified_skill_pairs(self) -> tuple[tuple[ProjectReviewSkill, bytes], ...]:
        if len(self._verified_contents) != len(self.skills):
            return ()
        return tuple(
            (skill, content)
            for skill, content in zip(self.skills, self._verified_contents)
            if content is not None
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "projectRoot": "<bound-project>",
            "profilePath": None if self.profile_path is None else ".selfworkflow/review.yaml",
            "profileHash": self.profile_hash,
            "schemaHash": self.schema_hash,
            "bindingHash": self.binding_hash,
            "skills": [skill.as_dict() for skill in self.skills],
            "reviewerManifest": [dict(item) for item in self.reviewer_manifest()],
            "reviewerManifests": {
                axis: [dict(item) for item in manifest]
                for axis, manifest in self.reviewer_manifests().items()
            },
            "blocking": self.blocking,
            "issues": list(self.issues),
        }


def _sha256(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _is_reparse(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return False
    except OSError:
        raise ProjectReviewProfileError from None
    return path.is_symlink() or bool(
        getattr(metadata, "st_file_attributes", 0) & _REPARSE_POINT
    )


def _profile_schema_path() -> Path:
    return Path(__file__).resolve().parents[2] / "schemas" / "project-review-profile.schema.json"


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _project_root(value: str | Path) -> Path:
    try:
        raw = Path(value)
        if not raw.is_absolute():
            raw = Path.cwd() / raw
        if any(_is_reparse(item) for item in (raw, *raw.parents)):
            raise ProjectReviewProfileError
        root = raw.resolve(strict=True)
    except (OSError, RuntimeError, TypeError):
        raise ProjectReviewProfileError from None
    if not root.is_dir() or _is_reparse(root):
        raise ProjectReviewProfileError
    return root


def _project_identity(root: Path) -> tuple[int, int]:
    """Return the volume and directory identity for the bound project root."""

    try:
        metadata = root.stat()
        device = int(metadata.st_dev)
        inode = int(metadata.st_ino)
    except (AttributeError, OSError, OverflowError, TypeError, ValueError):
        raise ProjectReviewProfileError from None
    if device < 0 or inode <= 0:
        raise ProjectReviewProfileError
    return device, inode


def _validated_relative_path(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ProjectReviewProfileError
    if value != unicodedata.normalize("NFC", value):
        raise ProjectReviewProfileError
    if "\\" in value or ":" in value or value.startswith("/"):
        raise ProjectReviewProfileError
    parts = value.split("/")
    if any(not part or part in {".", ".."} for part in parts):
        raise ProjectReviewProfileError
    if any(
        part.endswith((".", " "))
        or any(character in part for character in '<>"|?*')
        or part.split(".", 1)[0].casefold() in {
            "con", "prn", "aux", "nul",
            "com1", "com2", "com3", "com4", "com5", "com6", "com7", "com8", "com9",
            "lpt1", "lpt2", "lpt3", "lpt4", "lpt5", "lpt6", "lpt7", "lpt8", "lpt9",
        }
        for part in parts
    ):
        raise ProjectReviewProfileError
    if PureWindowsPath(value).drive or PureWindowsPath(value).root:
        raise ProjectReviewProfileError
    return value


def _skill_issue(
    root: Path, skill: ProjectReviewSkill,
) -> tuple[str | None, bytes | None, str | None]:
    target = root.joinpath(*skill.path.split("/"))
    try:
        if _is_reparse(target):
            raise ProjectReviewProfileError
        if not target.exists():
            return f"skill-missing:{skill.id}", None, None
        content = _read_bytes(target, MAX_SKILL_BYTES, root)
        content.decode("utf-8")
    except CatalogError as error:
        if "reparse" in error.reason or "path-changed" in error.reason:
            raise ProjectReviewProfileError from None
        if "resource-limit" in error.reason:
            return f"skill-too-large:{skill.id}", None, None
        return f"skill-read-failed:{skill.id}", None, None
    except (OSError, UnicodeError):
        return f"skill-read-failed:{skill.id}", None, None
    observed_hash = _sha256(content)
    if observed_hash != skill.content_hash:
        return f"skill-hash-mismatch:{skill.id}", None, observed_hash
    return None, content, observed_hash


def _as_mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ProjectReviewProfileError
    return dict(value)


def load_project_review_profile(project_root: str | Path) -> ProjectReviewProfile:
    """Load only the explicit ``.selfworkflow/review.yaml`` project profile."""

    root = _project_root(project_root)
    root_identity = _project_identity(root)
    profile_path = root / ".selfworkflow" / "review.yaml"
    if _is_reparse(profile_path.parent):
        raise ProjectReviewProfileError
    try:
        profile_metadata = profile_path.lstat()
    except FileNotFoundError:
        absent_binding = _sha256(_canonical_json({
            "projectRoot": str(root), "projectIdentity": root_identity,
            "profile": "absent",
        }))
        return ProjectReviewProfile(
            status="absent",
            project_root=str(root),
            profile_path=None,
            profile_hash=None,
            schema_hash=None,
            binding_hash=absent_binding,
            skills=(),
            issues=(),
            blocking=False,
            _profile_token=_PROFILE_TOKEN,
            _project_identity=root_identity,
            _observed_skill_hashes=(),
            _verified_contents=(),
        )
    except OSError:
        raise ProjectReviewProfileError from None
    if (
        profile_path.is_symlink()
        or bool(getattr(profile_metadata, "st_file_attributes", 0) & _REPARSE_POINT)
    ):
        raise ProjectReviewProfileError
    try:
        raw = _read_bytes(profile_path, MAX_PROFILE_BYTES, root)
        schema_path = _profile_schema_path()
        schema_bytes = _read_bytes(
            schema_path, MAX_PROFILE_BYTES, schema_path.parent,
        )
    except CatalogError:
        raise ProjectReviewProfileError from None
    except OSError:
        raise ProjectReviewProfileError from None
    try:
        raw.decode("utf-8")
        document = load_config_bytes(
            raw, schema_path, schema_bytes=schema_bytes
        )
    except (ConfigError, OSError, UnicodeError, RecursionError):
        raise ProjectReviewProfileError from None

    data = _as_mapping(document)
    entries = data.get("additionalReviewSkills")
    if not isinstance(entries, tuple):
        raise ProjectReviewProfileError
    skills: list[ProjectReviewSkill] = []
    ids: set[str] = set()
    for entry in entries:
        item = _as_mapping(entry)
        skill_id = item.get("id")
        if not isinstance(skill_id, str) or skill_id in ids:
            raise ProjectReviewProfileError
        ids.add(skill_id)
        path = _validated_relative_path(item.get("path"))
        content_hash = item.get("contentHash")
        required = item.get("required")
        if not isinstance(content_hash, str) or not isinstance(required, bool):
            raise ProjectReviewProfileError
        skills.append(ProjectReviewSkill(skill_id, path, content_hash, required))

    profile_hash = _sha256(raw)
    schema_hash = _sha256(schema_bytes)
    binding_value = {
        "projectRoot": str(root),
        "projectIdentity": root_identity,
        "profileHash": profile_hash,
        "schemaHash": schema_hash,
        "skills": [skill.as_dict() for skill in skills],
    }
    binding_hash = _sha256(_canonical_json(binding_value))
    issues_list: list[str] = []
    observed_skill_hashes: list[str | None] = []
    verified_contents: list[bytes | None] = []
    for skill in skills:
        issue, content, observed_hash = _skill_issue(root, skill)
        observed_skill_hashes.append(observed_hash)
        verified_contents.append(content)
        if issue is not None:
            issues_list.append(issue)
    issues = tuple(issues_list)
    blocking = any(
        issue.split(":", 1)[-1] in {skill.id for skill in skills if skill.required}
        for issue in issues
    )
    return ProjectReviewProfile(
        status="loaded" if not issues else "unverified",
        project_root=str(root),
        profile_path=str(profile_path),
        profile_hash=profile_hash,
        schema_hash=schema_hash,
        binding_hash=binding_hash,
        skills=tuple(skills),
        issues=issues,
        blocking=blocking,
        _profile_token=_PROFILE_TOKEN,
        _project_identity=root_identity,
        _observed_skill_hashes=tuple(observed_skill_hashes),
        _verified_contents=tuple(verified_contents) if not blocking else (),
    )


def session_binding_hash(
    profile: ProjectReviewProfile, conversation_id: str,
) -> str:
    """Bind the verified project profile to one host conversation identity."""

    if (
        type(conversation_id) is not str
        or not 1 <= len(conversation_id.encode("utf-8")) <= 256
        or conversation_id != unicodedata.normalize("NFC", conversation_id)
        or profile.binding_hash is None
        or type(profile) is not ProjectReviewProfile
        or not profile._is_valid()
    ):
        raise ProjectReviewProfileError
    return _sha256(_canonical_json({
        "conversationId": conversation_id,
        "profileBindingHash": profile.binding_hash,
    }))


def build_code_review_context(
    profile: ProjectReviewProfile,
    *,
    strength: str,
    is_code_task: bool,
    conversation_id: str | None,
) -> Mapping[str, object]:
    """Build the exact paired inputs a Host passes to both code reviewers."""

    if (
        type(profile) is not ProjectReviewProfile
        or not profile._is_valid()
        or strength not in {"Light", "Full", "Deep"}
        or type(is_code_task) is not bool
    ):
        raise ProjectReviewProfileError
    def issue_context(document: Mapping[str, object]) -> ProjectReviewContext:
        artifact = object.__new__(ProjectReviewContext)
        object.__setattr__(artifact, "_document", MappingProxyType(dict(document)))
        object.__setattr__(artifact, "_ProjectReviewContext__token", _CONTEXT_TOKEN)
        return artifact

    empty_manifest: tuple[Mapping[str, object], ...] = ()
    empty_bytes: tuple[bytes, ...] = ()
    if strength == "Light" or not is_code_task:
        reviewers = MappingProxyType({
            "standards": MappingProxyType({"manifest": empty_manifest, "skillBytes": empty_bytes}),
            "spec": MappingProxyType({"manifest": empty_manifest, "skillBytes": empty_bytes}),
        })
        return issue_context({
            "status": "not-applicable",
            "blocking": False,
            "sessionBindingHash": None,
            "issues": (),
            "reviewers": reviewers,
        })
    if type(conversation_id) is not str:
        raise ProjectReviewProfileError
    if profile.status == "absent":
        session_hash = session_binding_hash(profile, conversation_id)
        manifests = {"standards": empty_manifest, "spec": empty_manifest}
        skill_bytes = {"standards": empty_bytes, "spec": empty_bytes}
    else:
        session_hash = session_binding_hash(profile, conversation_id)
        manifests = profile.reviewer_manifests()
        skill_bytes = profile.reviewer_skill_bytes()
    reviewers = MappingProxyType({
        axis: MappingProxyType({
            "manifest": manifests[axis],
            "skillBytes": skill_bytes[axis],
        })
        for axis in ("standards", "spec")
    })
    return issue_context({
        "status": profile.status,
        "blocking": profile.blocking,
        "sessionBindingHash": session_hash,
        "issues": profile.issues,
        "reviewers": reviewers,
    })


@dataclass(frozen=True)
class ProjectReviewSession:
    """Conversation-scoped, single-read project Review profile."""

    profile: ProjectReviewProfile
    conversation_id: str
    binding_hash: str

    def _assert_current(self) -> None:
        """Reject reuse after the bound profile or any Skill has drifted."""

        current = load_project_review_profile(self.profile.project_root)
        if (
            current.binding_hash != self.profile.binding_hash
            or current.status != self.profile.status
            or current.issues != self.profile.issues
            or current.blocking != self.profile.blocking
            or current._project_identity != self.profile._project_identity
            or current._observed_skill_hashes != self.profile._observed_skill_hashes
        ):
            raise ProjectReviewProfileError

    def code_review_context(
        self, *, strength: str, is_code_task: bool
    ) -> Mapping[str, object]:
        if strength in {"Full", "Deep"} and is_code_task:
            self._assert_current()
        return build_code_review_context(
            self.profile,
            strength=strength,
            is_code_task=is_code_task,
            conversation_id=self.conversation_id,
        )


def start_project_review_session(
    project_root: str | Path, conversation_id: str
) -> ProjectReviewSession:
    """Read the explicit profile once and bind it to one conversation."""

    profile = load_project_review_profile(project_root)
    return ProjectReviewSession(
        profile=profile,
        conversation_id=conversation_id,
        binding_hash=session_binding_hash(profile, conversation_id),
    )
