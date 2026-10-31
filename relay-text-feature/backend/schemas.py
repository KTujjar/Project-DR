"""The contract shared by the text API and the dashboard."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MessageInput(StrictModel):
    conversation_id: str = Field(min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_-]+$")
    text: str = Field(min_length=1, max_length=4000)


class IntakeInput(MessageInput):
    sender_name: str = Field(default="Community member", max_length=80)
    contact: str = Field(default="", max_length=100)
    reported_location: str = Field(default="", max_length=200)
    channel: Literal["web", "demo"] = "web"


class ReviewedReply(StrictModel):
    text: str = Field(min_length=1, max_length=4000)
    awaiting_information: bool = False


class Need(StrictModel):
    item: str | None = Field(description="Requested item, or null if unknown.")
    quantity: int | None = Field(strict=True, gt=0, description="Explicit requested item count; never infer from people or household size.")
    unit: str | None = Field(description="Explicit unit such as packs or bottles, or null.")


class Evidence(StrictModel):
    message_id: str
    quote: str = Field(min_length=1, max_length=1000)


class Interpretation(StrictModel):
    purposes: list[Literal["question", "assistance_request", "delivery_update", "problem_report", "offer", "other"]]
    needs: list[Need]
    location: str | None
    access_barriers: list[str]
    delivery_report: str | None = Field(description="A reported update, never verified delivery or an inventory change.")
    responder_summary: str = Field(max_length=1500)
    faq_ids: list[str] = Field(description="IDs of reference entries directly answering the question; no invented IDs.")
    unanswered_questions: list[str] = Field(description="Questions not answered by the reference entries, including unanswered parts of a compound question.")
    evidence: list[Evidence] = Field(description="Verbatim community quotes supporting extracted facts, with their message IDs.")
