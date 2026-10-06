"""Validated request and response shapes for durable web jobs."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

RefreshPart = Literal["listings", "disk", "sonarr"]


def _default_refresh_parts() -> list[RefreshPart]:
    return ["listings", "disk", "sonarr"]


class Target(BaseModel):
    model_config = ConfigDict(extra="forbid")
    platform: Literal["youtube", "dropout"]
    slug: str = Field(min_length=1, max_length=200)


class RefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["refresh"]
    items: list[Target] = Field(min_length=1, max_length=500)
    source_index: int | None = Field(default=None, ge=0)
    expected_revision: str | None = Field(default=None, min_length=1, max_length=128)
    parts: list[RefreshPart] = Field(
        default_factory=_default_refresh_parts, min_length=1, max_length=3
    )

    @model_validator(mode="after")
    def validate_scope(self) -> "RefreshRequest":
        if self.source_index is not None and len(self.items) != 1:
            raise ValueError("source_index requires exactly one refresh target")
        if len(set(self.parts)) != len(self.parts):
            raise ValueError("refresh parts must be unique")
        return self


class DownloadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["download"]
    ids: list[str] = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def validate_ids(self) -> "DownloadRequest":
        if len(set(self.ids)) != len(self.ids):
            raise ValueError("ids must be unique")
        if any(not item or len(item) > 512 for item in self.ids):
            raise ValueError("invalid selected action id")
        return self


class CheckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["check"]
    items: list[Target] = Field(min_length=1, max_length=20)


class DiagnosticsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["diagnostics"]
    checks: list[Literal["paths", "cookies", "ffmpeg", "node", "sonarr", "worker", "database"]] = (
        Field(min_length=1, max_length=7)
    )


JobRequest = Annotated[
    RefreshRequest | DownloadRequest | CheckRequest | DiagnosticsRequest,
    Field(discriminator="kind"),
]
job_request_adapter: TypeAdapter[JobRequest] = TypeAdapter(JobRequest)


class JobStart(BaseModel):
    job_id: str
    status: Literal["queued"]


class JobLog(BaseModel):
    n: int = Field(ge=1)
    ts: str
    line: str = Field(max_length=4096)


class JobSnapshot(BaseModel):
    id: str
    kind: Literal["refresh", "download", "check", "diagnostics"]
    status: Literal[
        "queued", "running", "stopping", "succeeded", "failed", "cancelled", "interrupted"
    ]
    created_at: str
    started_at: str | None
    finished_at: str | None
    progress: dict[str, object] | None
    result: object | None
    error: object | None
    logs: list[JobLog]
    log_cursor: int = Field(ge=0)
    logs_truncated: bool
    can_cancel: bool
    can_retry: bool


class JobList(BaseModel):
    active: JobSnapshot | None
    history: list[JobSnapshot]
    total: int = Field(ge=0)


class ErrorResponse(BaseModel):
    error: str | dict[str, object]
    code: str
    request_id: str
    job_id: str | None = None
