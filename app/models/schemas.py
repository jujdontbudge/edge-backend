from datetime import datetime
from enum import Enum
from pydantic import AliasChoices, BaseModel, EmailStr, Field, computed_field


class Topic(str, Enum):
    probability = "probability"
    expected_value = "expected_value"
    mental_math = "mental_math"
    combinatorics = "combinatorics"
    market_making = "market_making"
    statistics = "statistics"
    game_theory = "game_theory"
    discrete_math = "discrete_math"


class AnswerType(str, Enum):
    numeric = "numeric"
    self_graded = "self_graded"


class SelfGrade(str, Enum):
    got_it = "got_it"
    did_not_get_it = "did_not_get_it"


class SolutionStep(BaseModel):
    id: int
    title: str
    math: str


class Question(BaseModel):
    id: str
    prompt: str
    topic: Topic
    level: int = Field(..., ge=1, le=5, validation_alias=AliasChoices("level", "difficulty"))
    answer_type: AnswerType
    numeric_answer: float | None = None
    tolerance_percent: float | None = None
    tolerance_absolute: float | None = None
    is_exact_integer: bool = False
    solution_steps: list[SolutionStep]
    firm_style: str | None = None
    find_expression: str | None = None
    version: int = 1

    @computed_field
    @property
    def level_label(self) -> str:
        return f"Level {self.level}"


class DailySetResponse(BaseModel):
    id: str
    date: str
    questions: list[Question]


class AttemptSubmit(BaseModel):
    question_id: str
    numeric_answer: float | None = None
    self_grade: SelfGrade | None = None
    submitted_answer: str | None = Field(default=None, max_length=5000)
    solve_time_seconds: int = Field(..., ge=0, le=7200)
    attempts_used: int = Field(default=1, ge=1, le=99)
    attempt_limit: int = Field(default=1, ge=1, le=99)
    revealed: bool = False


class AttemptResponse(BaseModel):
    id: str
    question_id: str
    is_correct: bool
    correct_answer: float | None = None
    solve_time_seconds: int
    attempts_used: int
    attempt_limit: int
    revealed: bool
    timestamp: str


class StreakResponse(BaseModel):
    current: int
    longest: int
    total_solved: int
    freezes_remaining: int
    last_active_date: str | None = None


class StatsResponse(BaseModel):
    streak: StreakResponse
    accuracy_30d: float
    accuracy_7d: float
    accuracy_delta_7d: float
    accuracy_all: float
    avg_attempts_30d: float
    avg_attempts_7d: float
    reveal_rate_30d: float
    reveal_rate_7d: float
    trend_7d: list[dict]
    weak_spots: list[dict]
    best_spots: list[dict]
    topic_scores: list[dict]
    overall_score: int
    by_topic: dict[str, dict]
    total_attempted: int


class TutorMessageRequest(BaseModel):
    question_id: str | None = None
    message: str = Field(..., min_length=1, max_length=2000)
    conversation_id: str | None = None


class TutorUsageResponse(BaseModel):
    used_today: int
    limit: int
    remaining: int


class TutorMessageResponse(BaseModel):
    id: str
    conversation_id: str
    role: str
    content: str
    created_at: str


class TutorConversationSummary(BaseModel):
    conversation_id: str
    title: str
    last_message: str
    updated_at: str
    message_count: int


class TutorConversationMessagesResponse(BaseModel):
    conversation_id: str
    title: str | None = None
    messages: list[TutorMessageResponse]


class TutorConversationUpdate(BaseModel):
    title: str = Field(..., min_length=1, max_length=80)


class UserProfile(BaseModel):
    id: str
    email: EmailStr | None = None
    display_name: str | None = Field(default=None, max_length=100)
    daily_goal: int = 7
    attempt_limit: int = 3
    target_firms: list[str] = []
    interview_timeline: str | None = None
    entitlement: str = "free"
    created_at: str


class OnboardingRequest(BaseModel):
    daily_goal: int = Field(default=7, ge=1, le=50)
    attempt_limit: int = Field(default=3, ge=1, le=99)
    target_firms: list[str] = Field(default=[], max_length=10)
    interview_timeline: str | None = Field(default=None, max_length=100)


class EvaluateRequest(BaseModel):
    question_id: str = Field(..., min_length=1, max_length=100)
    user_answer: str = Field(..., min_length=1, max_length=5000)


class EvaluateResponse(BaseModel):
    correct: bool
    feedback: str
