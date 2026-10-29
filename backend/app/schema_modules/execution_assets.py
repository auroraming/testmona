from pydantic import AliasChoices, BaseModel, ConfigDict, EmailStr, field_validator, HttpUrl, model_validator, Field
from typing import List, Optional, Dict, Any, Union
from datetime import datetime
from ..models import Priority, Status, TestStatus, ResultStatus, Role, Permission, CustomFieldType, TestType, RecycleBinType, RequirementStatus, DefectStatus, DefectSeverity, DefectPriority, DefectLinkType, MilestoneStatus, NotificationType, StepCategory, StepComplexity, DocStatus
import re
import html
import json

from .versioning import (
    DateValidationRules,
    NumberValidationRules,
    SelectValidationRules,
    TestCaseVersionBase,
    TestCaseVersionCreate,
    TestCaseVersionUpdate,
    TextValidationRules,
    VersionComparisonBase,
    VersionComparisonCreate,
    VersionLockBase,
    VersionLockCreate,
    VersionTagBase,
    VersionTagCreate,
)
from ..services.webhook_security import normalize_webhook_url

from .core import *
from .custom_fields import *
from .integrations_settings import *
from .requirements import *
from .defects import *
from .planning import *
from .notifications_analytics import *


TEST_DEBT_TYPES = {"stale", "duplicate", "orphan", "always_pass", "never_run", "no_requirement_link"}
TEST_DEBT_SEVERITIES = {"low", "medium", "high", "critical"}
TEST_DEBT_ACTIONS = {"update", "merge", "archive", "link_req", "review"}
AI_AUTOMATION_RUNNER_TYPES = {"web", "mobile", "api"}
AI_AUTOMATION_EXECUTION_MODES = {"ai", "script"}
AI_AUTOMATION_EVIDENCE_TYPES = {"step", "assertion", "log", "screenshot", "trace", "network"}


def _contains_inline_secret(value: Any) -> bool:
    forbidden = {"apikey", "authorization", "password", "secret", "token", "accesstoken"}
    if isinstance(value, dict):
        for key, child in value.items():
            normalized_key = re.sub(r"[^a-z0-9]", "", str(key).lower())
            if normalized_key in forbidden or normalized_key.endswith(tuple(forbidden)):
                return True
            if _contains_inline_secret(child):
                return True
    elif isinstance(value, list):
        return any(_contains_inline_secret(child) for child in value)
    return False


class TestDebtItemBase(BaseModel):
    test_case_id: int = Field(..., ge=1)
    debt_type: str = Field(..., min_length=1, max_length=40)
    severity: str = Field("medium", min_length=1, max_length=20)
    suggested_action: str = Field(..., min_length=1, max_length=40)
    details: Optional[str] = Field(None, max_length=2000)

    @field_validator("debt_type")
    @classmethod
    def validate_debt_type(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in TEST_DEBT_TYPES:
            raise ValueError("Unsupported debt type")
        return normalized

    @field_validator("severity")
    @classmethod
    def validate_severity(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in TEST_DEBT_SEVERITIES:
            raise ValueError("Unsupported severity")
        return normalized

    @field_validator("suggested_action")
    @classmethod
    def validate_suggested_action(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in TEST_DEBT_ACTIONS:
            raise ValueError("Unsupported suggested action")
        return normalized

    @field_validator("details")
    @classmethod
    def validate_details(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class TestDebtItemCreate(TestDebtItemBase):
    pass


class TestDebtItemUpdate(BaseModel):
    # ``resolved_at`` is deliberately absent: the resolve/reopen endpoints own
    # that transition, so a plain PATCH cannot sidestep the
    # is_false_positive/resolved_at invariant or write a naive datetime.
    # extra="forbid" so a client still sending resolved_at gets a clear 422
    # rather than a silent no-op.
    model_config = ConfigDict(extra="forbid")

    severity: Optional[str] = Field(None, min_length=1, max_length=20)
    suggested_action: Optional[str] = Field(None, min_length=1, max_length=40)
    details: Optional[str] = Field(None, max_length=2000)

    @field_validator("severity")
    @classmethod
    def validate_update_severity(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip().lower()
        if normalized not in TEST_DEBT_SEVERITIES:
            raise ValueError("Unsupported severity")
        return normalized

    @field_validator("suggested_action")
    @classmethod
    def validate_update_suggested_action(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip().lower()
        if normalized not in TEST_DEBT_ACTIONS:
            raise ValueError("Unsupported suggested action")
        return normalized

    @field_validator("details")
    @classmethod
    def validate_update_details(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class TestDebtItemTestCase(BaseModel):
    id: int
    project_seq: Optional[int] = None
    title: str
    priority: Optional[str] = None
    status: Optional[str] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class TestDebtItem(TestDebtItemBase):
    id: int
    project_id: int
    auto_detected: bool
    is_false_positive: bool = False
    false_positive_reason: Optional[str] = None
    resolved_at: Optional[datetime] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    test_case: Optional[TestDebtItemTestCase] = None

    class Config:
        from_attributes = True


class TestAssetHealthSummary(BaseModel):
    total_cases: int
    active_debt_items: int
    resolved_debt_items: int
    false_positive_items: int = 0
    affected_cases: int = 0
    healthy_cases: int = 0
    health_score: int = 100
    by_debt_type: Dict[str, int]
    by_severity: Dict[str, int]
    by_action: Dict[str, int] = {}
    last_detected_at: Optional[datetime] = None


class TestAssetDebtDetectionResult(BaseModel):
    created: int
    updated: int
    auto_resolved: int
    active_debt_items: int
    summary: TestAssetHealthSummary


class TestDebtBulkResolve(BaseModel):
    item_ids: List[int] = Field(..., min_length=1, max_length=500)


class TestDebtFalsePositive(BaseModel):
    reason: Optional[str] = Field(None, max_length=2000)

    @field_validator("reason")
    @classmethod
    def validate_fp_reason(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class TestDebtBulkFalsePositive(BaseModel):
    item_ids: List[int] = Field(..., min_length=1, max_length=500)
    reason: Optional[str] = Field(None, max_length=2000)

    @field_validator("reason")
    @classmethod
    def validate_bulk_fp_reason(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class TestDebtBulkResolveResult(BaseModel):
    resolved: int
    # Ids that were not touched (wrong project, already resolved, already a
    # false positive, or nonexistent) so a partial bulk action is never
    # reported as a full success.
    skipped_ids: List[int] = Field(default_factory=list)
    summary: TestAssetHealthSummary

class SharedStepBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=500)
    action: str = Field(..., min_length=1, max_length=1000)
    expected_result: str = Field(..., min_length=1, max_length=1000)
    project_id: int = Field(..., ge=1)
    is_active: bool = True
    usage_count: int = 0

    @field_validator('name', 'action', 'expected_result')
    @classmethod
    def validate_shared_step_required_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError('Field is required')
        return cleaned

    @field_validator('description')
    @classmethod
    def validate_shared_step_description(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        cleaned = value.strip()
        return cleaned or None


class SharedStepCreate(SharedStepBase):
    pass


class SharedStepUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=500)
    action: Optional[str] = Field(None, min_length=1, max_length=1000)
    expected_result: Optional[str] = Field(None, min_length=1, max_length=1000)
    is_active: Optional[bool] = None

    @field_validator('name', 'action', 'expected_result')
    @classmethod
    def validate_shared_step_update_required_text(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        cleaned = value.strip()
        if not cleaned:
            raise ValueError('Field is required')
        return cleaned

    @field_validator('description')
    @classmethod
    def validate_shared_step_update_description(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        cleaned = value.strip()
        return cleaned or None


class SharedStep(SharedStepBase):
    id: int
    project_seq: Optional[int] = None  # per-project sequence (URLs/badges)
    created_by: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# Global Parameter Schemas
class GlobalParameterBase(BaseModel):
    name: str
    value: str
    description: Optional[str] = None
    parameter_type: str = "string"
    project_id: Optional[int] = None
    is_active: bool = True
    is_encrypted: bool = False


class GlobalParameterCreate(GlobalParameterBase):
    # Set server-side from the authenticated user; never trusted from the client.
    created_by: Optional[int] = None


class GlobalParameterUpdate(BaseModel):
    """Mutable fields of an existing parameter.

    ``project_id`` is intentionally absent. Permission is checked against the
    *stored* project, so accepting it here would let a project-scoped writer
    promote their parameter into the admin-only global scope (``null``) or plant
    one inside a project they cannot access. Scope is chosen at creation time and
    never changes afterwards.
    """
    name: Optional[str] = None
    value: Optional[str] = None
    description: Optional[str] = None
    parameter_type: Optional[str] = None
    is_active: Optional[bool] = None
    is_encrypted: Optional[bool] = None


class GlobalParameter(GlobalParameterBase):
    id: int
    project_seq: Optional[int] = None  # per-project sequence (URLs/badges)
    created_by: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# Test Dataset (case-level parameterization) Schemas
def _normalize_dataset(parameters, rows):
    """Validate a dataset's columns + rows.

    ``parameters`` must be a non-empty list of unique, trimmed column names.
    Every row key must be one of those columns; missing keys default to "".
    Returns the cleaned ``(parameters, rows)`` tuple.
    """
    if not isinstance(parameters, list) or not parameters:
        raise ValueError("parameters must be a non-empty list of column names")
    cleaned_params: List[str] = []
    for raw in parameters:
        name = str(raw).strip()
        if not name:
            raise ValueError("parameter names cannot be empty")
        if name in cleaned_params:
            raise ValueError(f"duplicate parameter name: {name}")
        cleaned_params.append(name)
    param_set = set(cleaned_params)

    if rows is None:
        rows = []
    if not isinstance(rows, list):
        raise ValueError("rows must be a list of objects")
    cleaned_rows: List[Dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("each row must be an object mapping parameter -> value")
        unknown = set(row.keys()) - param_set
        if unknown:
            raise ValueError(f"row has unknown parameters: {sorted(unknown)}")
        cleaned_rows.append({p: ("" if row.get(p) is None else str(row.get(p))) for p in cleaned_params})
    return cleaned_params, cleaned_rows


class TestDatasetBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=150)
    description: Optional[str] = None
    parameters: List[str] = Field(default_factory=list)
    rows: List[Dict[str, Any]] = Field(default_factory=list)
    is_active: bool = True


class TestDatasetCreate(TestDatasetBase):
    project_id: int

    @model_validator(mode="after")
    def _validate(self):
        self.parameters, self.rows = _normalize_dataset(self.parameters, self.rows)
        return self


class TestDatasetUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=150)
    description: Optional[str] = None
    parameters: Optional[List[str]] = None
    rows: Optional[List[Dict[str, Any]]] = None
    is_active: Optional[bool] = None

    @model_validator(mode="after")
    def _validate(self):
        # Only validate when either side of the table is being changed; the
        # caller may PATCH just the name/description.
        if self.parameters is not None or self.rows is not None:
            if self.parameters is None:
                raise ValueError("parameters is required when rows are provided")
            self.parameters, self.rows = _normalize_dataset(self.parameters, self.rows or [])
        return self


class TestDataset(TestDatasetBase):
    id: int
    project_seq: Optional[int] = None  # per-project sequence (URLs/badges)
    project_id: int
    created_by: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# Test Mindmap Schemas
class TestMindmapBase(BaseModel):
    name: str
    description: Optional[str] = None
    project_id: int
    mindmap_data: Optional[dict] = None
    is_active: bool = True


class TestMindmapCreate(TestMindmapBase):
    pass


class TestMindmapUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    mindmap_data: Optional[dict] = None
    is_active: Optional[bool] = None


class TestMindmap(TestMindmapBase):
    id: int
    created_by: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class TestMindmapLinkCreate(BaseModel):
    test_case_ids: List[int] = Field(min_length=1, max_length=500)


class TestMindmapLinkedTestCase(BaseModel):
    id: int
    project_seq: Optional[int] = None
    title: str
    priority: Optional[str] = None
    status: Optional[str] = None
    test_suite_id: int
    section_id: Optional[int] = None
    node_id: str


class TestCaseMindmapLink(BaseModel):
    mindmap_id: int
    mindmap_name: str
    node_id: str
    node_title: Optional[str] = None


# Impact Analysis Schemas
class ImpactAnalysisBase(BaseModel):
    title: str
    description: Optional[str] = None
    entity_type: str
    entity_id: int
    change_type: str
    project_id: int
    impact_data: Optional[dict] = None
    status: str = "pending"


class ImpactAnalysisCreate(ImpactAnalysisBase):
    created_by: int


class ImpactAnalysisUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    impact_data: Optional[dict] = None
    status: Optional[str] = None


class ImpactAnalysis(ImpactAnalysisBase):
    id: int
    created_by: int
    created_at: datetime

    class Config:
        from_attributes = True


# Execution Environment Schemas
class ExecutionEnvironmentBase(BaseModel):
    name: str
    description: Optional[str] = None
    environment_type: str
    config_data: Optional[dict] = None
    build_info: Optional[dict] = None
    is_active: bool = True


class ExecutionEnvironmentCreate(ExecutionEnvironmentBase):
    project_id: int


class ExecutionEnvironmentUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    environment_type: Optional[str] = None
    config_data: Optional[dict] = None
    build_info: Optional[dict] = None
    is_active: Optional[bool] = None


class ExecutionEnvironment(ExecutionEnvironmentBase):
    id: int
    project_seq: Optional[int] = None  # per-project sequence (URLs/badges)
    project_id: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# Test Schedule Schemas
class TestScheduleBase(BaseModel):
    name: str
    description: Optional[str] = None
    schedule_type: str
    schedule_config: Optional[dict] = None
    is_active: bool = True


class TestScheduleCreate(TestScheduleBase):
    project_id: int
    test_suite_id: Optional[int] = None
    environment_id: Optional[int] = None
    created_by: int


class TestScheduleUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    schedule_type: Optional[str] = None
    schedule_config: Optional[dict] = None
    is_active: Optional[bool] = None
    test_suite_id: Optional[int] = None
    environment_id: Optional[int] = None


class TestSchedule(TestScheduleBase):
    id: int
    project_id: int
    test_suite_id: Optional[int] = None
    environment_id: Optional[int] = None
    created_by: int
    last_run: Optional[datetime] = None
    next_run: Optional[datetime] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# Execution Engine Schemas
class ExecutionEngineBase(BaseModel):
    name: str
    engine_type: str
    config_data: Optional[dict] = None
    max_concurrent_runs: int = 10
    is_active: bool = True


class ExecutionEngineCreate(ExecutionEngineBase):
    pass


class ExecutionEngineUpdate(BaseModel):
    name: Optional[str] = None
    engine_type: Optional[str] = None
    config_data: Optional[dict] = None
    max_concurrent_runs: Optional[int] = None
    is_active: Optional[bool] = None


class ExecutionEngine(ExecutionEngineBase):
    id: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# Execution Log Schemas
class ExecutionLogBase(BaseModel):
    log_level: str
    message: str
    metadata: Optional[dict] = None


class ExecutionLogCreate(ExecutionLogBase):
    test_run_id: int
    test_result_id: Optional[int] = None


class ExecutionLog(ExecutionLogBase):
    id: int
    test_run_id: int
    test_result_id: Optional[int] = None
    timestamp: datetime

    class Config:
        from_attributes = True


# Test Run Environment Schemas
class TestRunEnvironmentBase(BaseModel):
    config_snapshot: Optional[dict] = None
    build_snapshot: Optional[dict] = None


class TestRunEnvironmentCreate(TestRunEnvironmentBase):
    test_run_id: int
    environment_id: int


class TestRunEnvironment(TestRunEnvironmentBase):
    id: int
    test_run_id: int
    environment_id: int
    created_at: datetime

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# API tokens
# ---------------------------------------------------------------------------


class ApiTokenCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    expires_at: Optional[datetime] = None


class ApiTokenView(BaseModel):
    """Token view safe to expose — never includes the raw secret."""
    id: int
    name: str
    prefix: str
    last_used_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True


class ApiTokenCreated(ApiTokenView):
    """One-time response that includes the raw secret."""
    token: str


# ---------------------------------------------------------------------------
# Webhooks
# ---------------------------------------------------------------------------


class WebhookSubscriptionBase(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    url: str = Field(min_length=1, max_length=2048)
    events: List[str] = Field(min_length=1)
    is_active: bool = True

    @field_validator("url")
    @classmethod
    def _validate_url(cls, value: str) -> str:
        return normalize_webhook_url(value)


class WebhookSubscriptionCreate(WebhookSubscriptionBase):
    project_id: int


class WebhookSubscriptionUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=120)
    url: Optional[str] = Field(default=None, max_length=2048)
    events: Optional[List[str]] = None
    is_active: Optional[bool] = None
    rotate_secret: bool = False

    @field_validator("url")
    @classmethod
    def _validate_url(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        return normalize_webhook_url(value)


class WebhookSubscriptionView(BaseModel):
    """Public view of a subscription — never includes the secret."""
    id: int
    project_id: int
    name: str
    url: str
    events: List[str]
    is_active: bool
    created_by: Optional[int] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class WebhookSubscriptionCreated(WebhookSubscriptionView):
    """One-time response that includes the secret so the user can copy it."""
    secret: str


class SavedFilterBase(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    scope: str = Field(min_length=1, max_length=32)
    definition: Dict[str, Any]
    is_default: bool = False
    is_shared: bool = False


class SavedFilterCreate(SavedFilterBase):
    project_id: int


class SavedFilterUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=120)
    definition: Optional[Dict[str, Any]] = None
    is_default: Optional[bool] = None
    is_shared: Optional[bool] = None


class SavedFilterView(SavedFilterBase):
    id: int
    user_id: int
    project_id: int
    created_at: datetime
    updated_at: Optional[datetime] = None
    owned_by_current_user: bool = False

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Bulk edit
# ---------------------------------------------------------------------------


class BulkTestCaseUpdate(BaseModel):
    ids: List[int] = Field(min_length=1, max_length=2000)
    priority: Optional[Priority] = None
    status: Optional[str] = Field(default=None, max_length=20)
    test_type: Optional[str] = Field(default=None, max_length=20)
    section_id: Optional[int] = None
    # Normalized tag names. ``tags`` replaces the whole set; add/remove patch it.
    tags: Optional[List[str]] = None
    add_tags: Optional[List[str]] = None
    remove_tags: Optional[List[str]] = None

    @field_validator("status")
    @classmethod
    def _status_lower(cls, value):
        if value is None:
            return value
        v = value.strip().lower()
        return v or None

    @field_validator("test_type")
    @classmethod
    def _type_lower(cls, value):
        if value is None:
            return value
        v = value.strip().lower()
        return v or None


class BulkDefectUpdate(BaseModel):
    ids: List[int] = Field(min_length=1, max_length=2000)
    status: Optional[DefectStatus] = None
    severity: Optional[DefectSeverity] = None
    priority: Optional[DefectPriority] = None
    assigned_to: Optional[int] = None
    clear_assignee: bool = False


class BulkUpdateResult(BaseModel):
    updated: int
    skipped_ids: List[int] = Field(default_factory=list)
    reason: Optional[str] = None


class WebhookDeliveryView(BaseModel):
    id: int
    subscription_id: int
    event: str
    status: str
    attempts: int
    response_status: Optional[int] = None
    response_body: Optional[str] = None
    error: Optional[str] = None
    delivered_at: Optional[datetime] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class AIAutomationTaskCreate(BaseModel):
    project_id: int = Field(..., ge=1)
    runner_type: str = Field(..., min_length=1, max_length=20)
    execution_mode: str = Field("ai", min_length=1, max_length=20)
    goal: str = Field(..., min_length=1, max_length=4000)
    test_case_id: Optional[int] = Field(None, ge=1)
    test_run_id: Optional[int] = Field(None, ge=1)
    environment_id: Optional[int] = Field(None, ge=1)
    max_steps: int = Field(50, ge=1, le=500)
    timeout_seconds: int = Field(900, ge=30, le=86400)
    token_budget: Optional[int] = Field(None, ge=1, le=10_000_000)
    config: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("runner_type")
    @classmethod
    def validate_runner_type(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in AI_AUTOMATION_RUNNER_TYPES:
            raise ValueError("runner_type must be web, mobile, or api")
        return normalized

    @field_validator("execution_mode")
    @classmethod
    def validate_execution_mode(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in AI_AUTOMATION_EXECUTION_MODES:
            raise ValueError("execution_mode must be ai or script")
        return normalized

    @field_validator("goal")
    @classmethod
    def normalize_goal(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("goal cannot be empty")
        return normalized

    @field_validator("config")
    @classmethod
    def reject_inline_secrets(cls, value: Dict[str, Any]) -> Dict[str, Any]:
        if _contains_inline_secret(value):
            raise ValueError("config must use credential references and cannot contain inline secrets")
        if len(json.dumps(value, ensure_ascii=False, separators=(",", ":"))) > 65536:
            raise ValueError("config cannot exceed 64 KB")
        return value


class AIAutomationTask(BaseModel):
    id: int
    project_id: int
    test_case_id: Optional[int] = None
    test_run_id: Optional[int] = None
    environment_id: Optional[int] = None
    requested_by: int
    runner_type: str
    execution_mode: str
    status: str
    goal: str
    max_steps: int
    timeout_seconds: int
    token_budget: Optional[int] = None
    input_tokens: int
    output_tokens: int
    runner_id: Optional[int] = None
    lease_expires_at: Optional[datetime] = None
    attempt_count: int
    config: Dict[str, Any]
    result: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    cancel_requested_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class AIAutomationRunnerCreate(BaseModel):
    project_id: int = Field(..., ge=1)
    name: str = Field(..., min_length=1, max_length=120)
    runner_type: str = Field(..., min_length=1, max_length=20)
    capabilities: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("name cannot be empty")
        return normalized

    @field_validator("runner_type")
    @classmethod
    def validate_runner_type(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in AI_AUTOMATION_RUNNER_TYPES:
            raise ValueError("runner_type must be web, mobile, or api")
        return normalized


class AIAutomationRunner(BaseModel):
    id: int
    project_id: int
    name: str
    runner_type: str
    token_prefix: str
    capabilities: Dict[str, Any]
    status: str
    last_seen_at: Optional[datetime] = None
    created_by: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class AIAutomationRunnerCreated(AIAutomationRunner):
    token: str


class AIAutomationTaskLease(BaseModel):
    task: AIAutomationTask
    lease_token: str


class AIAutomationRunnerHeartbeat(BaseModel):
    task_id: Optional[int] = Field(None, ge=1)
    lease_token: Optional[str] = Field(None, min_length=20, max_length=200)


class AIAutomationRunnerHeartbeatResult(BaseModel):
    runner_status: str
    cancel_requested: bool = False
    lease_expires_at: Optional[datetime] = None


class AIAutomationTaskReport(BaseModel):
    lease_token: str = Field(..., min_length=20, max_length=200)
    status: str = Field(..., min_length=1, max_length=30)
    result: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = Field(None, max_length=4000)
    input_tokens: int = Field(0, ge=0)
    output_tokens: int = Field(0, ge=0)

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"passed", "failed", "blocked", "timed_out", "cancelled"}:
            raise ValueError("status must be a terminal task status")
        return normalized


class AIAutomationEvidenceCreate(BaseModel):
    sequence: int = Field(..., ge=1, le=1_000_000)
    evidence_type: str = Field(..., min_length=1, max_length=30)
    title: str = Field(..., min_length=1, max_length=255)
    status: Optional[str] = Field(None, max_length=30)
    payload: Dict[str, Any] = Field(default_factory=dict)
    artifact_ref: Optional[str] = Field(None, max_length=500)

    @field_validator("evidence_type")
    @classmethod
    def validate_evidence_type(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in AI_AUTOMATION_EVIDENCE_TYPES:
            raise ValueError("unsupported evidence type")
        return normalized

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("title cannot be empty")
        return normalized

    @field_validator("payload")
    @classmethod
    def validate_payload(cls, value: Dict[str, Any]) -> Dict[str, Any]:
        if _contains_inline_secret(value):
            raise ValueError("evidence cannot contain inline secrets")
        if len(json.dumps(value, ensure_ascii=False, separators=(",", ":"))) > 65536:
            raise ValueError("evidence payload cannot exceed 64 KB")
        return value

    @field_validator("artifact_ref")
    @classmethod
    def validate_artifact_ref(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            return None
        if "://" in normalized or normalized.startswith(("/", "..")) or "../" in normalized:
            raise ValueError("artifact_ref must be a storage reference, not a URL or filesystem path")
        return normalized


class AIAutomationEvidence(BaseModel):
    id: int
    task_id: int
    sequence: int
    evidence_type: str
    title: str
    status: Optional[str] = None
    payload: Dict[str, Any]
    artifact_ref: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AIAutomationEvidenceBatch(BaseModel):
    lease_token: str = Field(..., min_length=20, max_length=200)
    items: List[AIAutomationEvidenceCreate] = Field(..., min_length=1, max_length=100)
