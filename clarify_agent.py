from pydantic import BaseModel, Field
from agents import Agent

INSTRUCTIONS = (
    "You are a research assistant helping to clarify ambiguous research queries through conversation. "
    "Given the user's initial research query and any previous Q&A exchanges, generate ONE insightful "
    "clarifying question that would help you better understand what they want to know. "
    "Focus on scope, depth, audience, specific aspects they care about most, and context. "
    "Make questions specific and actionable, not generic. Build on what you've already learned from "
    "previous answers to dig deeper."
)

class ClarifyingQuestion(BaseModel):
    question: str = Field(description="A specific clarifying question about the research topic")
    why_asking: str = Field(description="Brief explanation of why this question matters (1 sentence)")

clarify_agent = Agent(
    name="ClarifyAgent",
    instructions=INSTRUCTIONS,
    model="gpt-4o-mini",
    output_type=ClarifyingQuestion,
)
