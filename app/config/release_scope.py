"""Release capabilities default OFF; protected environments cannot opt in."""

from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ReleaseScope(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: Literal["development", "testing", "production", "staging"] = Field(
        default="development", alias="ENVIRONMENT",
    )
    payment_evidence_automation_enabled: bool = Field(
        default=False, alias="PAYMENT_EVIDENCE_AUTOMATION_ENABLED",
    )
    calendar_writes_enabled: bool = Field(default=False, alias="CALENDAR_WRITES_ENABLED")
    deployed_runtime: bool = Field(default=False, alias="DEPLOYED_RUNTIME")

    @model_validator(mode="after")
    def validate_release_scope(self) -> "ReleaseScope":
        if self.deployed_runtime and (
            "environment" not in self.model_fields_set
            or self.environment not in {"staging", "production"}
        ):
            raise ValueError("Deployed runtime requires explicit staging/production ENVIRONMENT")
        if self.environment in {"production", "staging"} and (
            self.payment_evidence_automation_enabled or self.calendar_writes_enabled
        ):
            raise ValueError("R10 release scope forbids payment automation and calendar writes")
        return self


def payment_automation_enabled() -> bool:
    return ReleaseScope().payment_evidence_automation_enabled


def require_simulation_environment() -> None:
    if ReleaseScope().environment not in {"development", "testing"}:
        raise ValueError("Simulation and fake adapters are forbidden in this environment")
