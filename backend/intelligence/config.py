"""Validated configuration and reproducible config identity for Person A.

Every knob here is read once from the environment and frozen. ``config_identity``
resolves the whole immutable manifest (code release, parser versions, prompt
hashes, policy versions, provider/model identity) into one string that a release
can be reproduced from; a bare ``v1`` would not be enough (handoff §17).
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field as dc_field
from pathlib import Path
from typing import Optional

from .types import PermanentProcessingError

# Version identities for everything that can change an extracted value.
CODE_RELEASE = "person-a-1.0.0"
PARSER_VERSIONS = {
    "text": "text-1.0.0",
    "pdf": "pdf-1.0.0",
    "docx": "docx-1.0.0",
    "xlsx": "xlsx-1.0.0",
}
POLICY_VERSIONS = {
    "aliases": "aliases-1.0.0",
    "ports": "ports-1.0.0",
    "units": "units-1.0.0",
    "normalization": "normalization-1.0.0",
    "comparison": "comparison-1.0.0",
    "classification": "classification-1.0.0",
    "roles": "roles-1.0.0",
}

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"

# Lifetime interaction budgets (contract §5). Person A reports unresolved
# targets against these; Person B persists the authoritative ledger.
MAX_DISTINCT_REVIEW_FIELDS = 2
MAX_ACCEPTED_DECISIONS_PER_FIELD = 2
MAX_ACCEPTED_DECISIONS_PER_FIELD_SIDE = 1
MAX_DOCUMENT_CHOICES_PER_ROLE = 1
MAX_DOCUMENT_CHOICES_PER_RUN = 2


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _env_bool(name: str, default: bool = False) -> bool:
    raw = _env(name)
    if not raw:
        return default
    if raw.lower() in ("1", "true", "yes", "on"):
        return True
    if raw.lower() in ("0", "false", "no", "off"):
        return False
    raise PermanentProcessingError(f"{name} must be a boolean, got {raw!r}")


def _env_int(name: str, default: int) -> int:
    raw = _env(name)
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise PermanentProcessingError(f"{name} must be an integer, got {raw!r}") from exc
    if value < 0:
        raise PermanentProcessingError(f"{name} must not be negative, got {value}")
    return value


# Interpretation of a lone thousands/decimal separator (handoff §15.5).
#   auto      - use convention evidence found inside the same document, else ambiguous
#   ambiguous - never resolve a lone separator
#   en        - ',' groups and '.' is the decimal separator
#   eu        - '.' groups and ',' is the decimal separator
NUMERIC_LOCALE_POLICIES = ("auto", "ambiguous", "en", "eu")


@dataclass(frozen=True)
class AIConfig:
    """Model-adapter configuration. Disabled by default; never guesses an endpoint."""

    enabled: bool = False
    provider: str = ""
    endpoint: str = ""
    deployment: str = ""
    api_version: str = ""
    model: str = ""
    api_key: str = dc_field(default="", repr=False)
    timeout_seconds: int = 30
    max_calls_per_run: int = 4
    allow_participant_content: bool = False

    def validate(self) -> None:
        if not self.enabled:
            return
        missing = [
            name
            for name, value in (
                ("INTELLIGENCE_AI_PROVIDER", self.provider),
                ("INTELLIGENCE_AI_ENDPOINT", self.endpoint),
                ("INTELLIGENCE_AI_MODEL", self.model),
                ("INTELLIGENCE_AI_API_KEY", self.api_key),
            )
            if not value
        ]
        if missing:
            raise PermanentProcessingError(
                "AI is enabled but these settings are unset: " + ", ".join(missing)
            )

    def identity(self) -> dict:
        """Provider identity for the config manifest. Never includes the key."""
        if not self.enabled:
            return {"enabled": False}
        return {
            "enabled": True,
            "provider": self.provider,
            "endpoint": self.endpoint,
            "deployment": self.deployment,
            "api_version": self.api_version,
            "model": self.model,
        }


@dataclass(frozen=True)
class IntelligenceConfig:
    """Frozen, validated Person A configuration."""

    source_root: Path
    demo_source_root: Path
    artifact_root: Path
    config_version: str = "person-a-v1"
    numeric_locale_policy: str = "auto"
    # A convention explicitly declared for a source registry. Empty means "let
    # the registry's own documents establish it, or stay ambiguous".
    source_numeric_convention: str = ""
    demo_numeric_convention: str = ""
    ocr_enabled: bool = False
    semantic_equivalence_enabled: bool = False
    allow_public_participant_ingest: bool = True
    max_source_bytes: int = 25 * 1024 * 1024
    max_pdf_pages: int = 200
    max_sheet_cells: int = 200_000
    ai: AIConfig = dc_field(default_factory=AIConfig)

    def validate(self) -> None:
        if self.numeric_locale_policy not in NUMERIC_LOCALE_POLICIES:
            raise PermanentProcessingError(
                "INTELLIGENCE_NUMERIC_LOCALE_POLICY must be one of "
                + ", ".join(NUMERIC_LOCALE_POLICIES)
            )
        for name, value in (("INTELLIGENCE_SOURCE_NUMERIC_CONVENTION", self.source_numeric_convention),
                            ("INTELLIGENCE_DEMO_NUMERIC_CONVENTION", self.demo_numeric_convention)):
            if value and value not in ("en", "eu"):
                raise PermanentProcessingError(f"{name} must be 'en', 'eu' or unset")
        if self.ocr_enabled:
            raise PermanentProcessingError(
                "INTELLIGENCE_OCR_ENABLED is set but no OCR engine is implemented; "
                "image-only documents are reported as an honest readability limit"
            )
        self.ai.validate()

    # -- reproducibility ---------------------------------------------------
    def prompt_hashes(self) -> dict:
        hashes = {}
        if PROMPTS_DIR.is_dir():
            for path in sorted(PROMPTS_DIR.glob("*.md")):
                hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
        return hashes

    def manifest(self) -> dict:
        """The complete immutable identity behind ``config_version``."""
        return {
            "config_version": self.config_version,
            "code_release": CODE_RELEASE,
            "parser_versions": dict(PARSER_VERSIONS),
            "policy_versions": dict(POLICY_VERSIONS),
            "prompt_hashes": self.prompt_hashes(),
            "numeric_locale_policy": self.numeric_locale_policy,
            "source_numeric_convention": self.source_numeric_convention,
            "demo_numeric_convention": self.demo_numeric_convention,
            "ocr_enabled": self.ocr_enabled,
            "semantic_equivalence_enabled": self.semantic_equivalence_enabled,
            "ai": self.ai.identity(),
        }

    def config_identity(self) -> str:
        """A stable digest of :meth:`manifest`, recorded on every run."""
        blob = json.dumps(self.manifest(), sort_keys=True, separators=(",", ":"))
        return f"{self.config_version}+{hashlib.sha256(blob.encode('utf-8')).hexdigest()[:16]}"


def load_config(env: Optional[dict] = None) -> IntelligenceConfig:
    """Build and validate the configuration from the process environment."""
    if env is not None:
        previous = dict(os.environ)
        os.environ.update({k: str(v) for k, v in env.items()})
        try:
            return load_config()
        finally:
            os.environ.clear()
            os.environ.update(previous)

    source_root = Path(_env("INTELLIGENCE_SOURCE_ROOT") or
                       str(REPO_ROOT / "resources" / "sdoc-hackathon-bundle")).resolve()
    demo_source_root = Path(_env("INTELLIGENCE_DEMO_SOURCE_ROOT") or
                            str(REPO_ROOT / "resources" / "demo-fixtures")).resolve()
    artifact_root = Path(_env("INTELLIGENCE_ARTIFACT_ROOT") or
                         str(REPO_ROOT / ".local" / "intelligence")).resolve()

    ai = AIConfig(
        enabled=_env_bool("INTELLIGENCE_AI_ENABLED", False),
        provider=_env("INTELLIGENCE_AI_PROVIDER"),
        endpoint=_env("INTELLIGENCE_AI_ENDPOINT"),
        deployment=_env("INTELLIGENCE_AI_DEPLOYMENT"),
        api_version=_env("INTELLIGENCE_AI_API_VERSION"),
        model=_env("INTELLIGENCE_AI_MODEL"),
        api_key=_env("INTELLIGENCE_AI_API_KEY"),
        timeout_seconds=_env_int("INTELLIGENCE_AI_TIMEOUT_SECONDS", 30),
        max_calls_per_run=_env_int("INTELLIGENCE_MAX_MODEL_CALLS_PER_RUN", 4),
        allow_participant_content=_env_bool("INTELLIGENCE_AI_ALLOW_PARTICIPANT_CONTENT", False),
    )

    config = IntelligenceConfig(
        source_root=source_root,
        demo_source_root=demo_source_root,
        artifact_root=artifact_root,
        config_version=_env("INTELLIGENCE_CONFIG_VERSION") or "person-a-v1",
        numeric_locale_policy=(_env("INTELLIGENCE_NUMERIC_LOCALE_POLICY") or "auto").lower(),
        source_numeric_convention=_env("INTELLIGENCE_SOURCE_NUMERIC_CONVENTION").lower(),
        demo_numeric_convention=_env("INTELLIGENCE_DEMO_NUMERIC_CONVENTION").lower(),
        ocr_enabled=_env_bool("INTELLIGENCE_OCR_ENABLED", False),
        semantic_equivalence_enabled=_env_bool("INTELLIGENCE_SEMANTIC_EQUIVALENCE_ENABLED", False),
        allow_public_participant_ingest=_env_bool(
            "INTELLIGENCE_ALLOW_PUBLIC_PARTICIPANT_INGEST", True
        ),
        ai=ai,
    )
    config.validate()
    return config
