# src/harness/api/schemas.py — request bodies (OpenAPI is generated from these)
"""Request models only; responses are the service layer's dicts (representative
shapes per 04 §5). Validation failures render as 422 validation_failed."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class LoginIn(BaseModel):
    username: str
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


class UserPatchIn(BaseModel):
    role_id: str | None = None
    is_active: bool | None = None


class IngestIn(BaseModel):
    source: str


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
