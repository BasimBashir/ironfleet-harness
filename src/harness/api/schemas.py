# src/harness/api/schemas.py — request bodies (OpenAPI is generated from these)
"""Request models only; responses are the service layer's dicts (representative
shapes per 04 §5). Validation failures render as 422 validation_failed."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class LoginIn(BaseModel):
    username: str
    password: str


class SignupIn(BaseModel):
    username: str
    password: str


class PasswordIn(BaseModel):
    password: str


class MatterIn(BaseModel):
    title: str
    client_ref: str | None = None
    matter_type: str | None = None
    jurisdiction: str | None = None
    confidentiality: str | None = None
    objectives: str | None = None
    priority: str | None = None


class MatterPatch(BaseModel):
    title: str | None = None
    client_ref: str | None = None
    matter_type: str | None = None
    jurisdiction: str | None = None
    confidentiality: str | None = None
    objectives: str | None = None
    priority: str | None = None


class ToIn(BaseModel):
    to: str
    note: str = ""


class MemberIn(BaseModel):
    role_id: str


class UserCreateIn(BaseModel):
    username: str
    password: str
    role_id: str = "reader"


class ProviderIn(BaseModel):        # M13.7: all optional — PATCH-shaped row edit
    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None      # write-only: never echoed back


class ProviderNewIn(BaseModel):     # M13.7 '+': an admin-added provider row
    name: str
    engine: str                     # ollama | llamacpp | vllm | mlx-lm | cloud
    base_url: str
    model: str
    api_key: str | None = None      # write-only: never echoed back


class AssignIn(BaseModel):          # M13.7: null clears back to auto
    provider: str | None = None


class UserPatchIn(BaseModel):
    role_id: str | None = None
    is_active: bool | None = None
    state: str | None = None


class IngestIn(BaseModel):
    source: str = ""   # empty = ingest this matter's own uploaded documents


class ReviewIn(BaseModel):
    decision: str
    note: str = ""


class WorkflowIn(BaseModel):
    name: str
    definition: Any


class ExecutionIn(BaseModel):
    task_text: str
    workflow_id: str | None = None
    plan_block: str | None = None


class ReasonIn(BaseModel):
    reason: str = ""


class RedirectIn(BaseModel):
    task_id: str
    instruction: str


class AgentIn(BaseModel):
    name: str
    role: str | None = None
    tool_policy: str | None = None
    default_task_class: str | None = None


class AgentPatch(BaseModel):
    name: str | None = None
    role: str | None = None
    tool_policy: str | None = None
    default_task_class: str | None = None


class TextIn(BaseModel):
    text: str


class NoteIn(BaseModel):
    note: str = ""


class RequestIn(BaseModel):
    kind: str = "info"
    question: str
    task_id: str | None = None


class AnswerIn(BaseModel):
    text: str = ""
    doc_ids: list[str] = []


class ConversationIn(BaseModel):
    title: str = ""


class MessageIn(BaseModel):
    text: str
    refs: list[str] = []


class FactsIn(BaseModel):
    updates: dict[str, Any]


class IntakeAnswerIn(BaseModel):
    question_id: str
    answer: Any
    doc_ids: list[str] = []


class DebriefIn(BaseModel):
    answers: dict[str, Any]
    doc_ids: list[str] = []


class DeadlineIn(BaseModel):
    # no `due` field: the kernel computes it (an extra `due` key is ignored)
    what: str
    service_date: str
    kind: str = "filing"
    days: int | None = None
    jurisdiction: str = "nz"
    region: str | None = None
    missed_consequence: str | None = None
    kernel_args: dict[str, Any] = {}
