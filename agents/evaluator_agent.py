from pydantic import BaseModel, Field
from agents import Agent

INSTRUCTIONS = (
    "You are a research report quality evaluator. "
    "Review the research report for:\n"
    "1. Accuracy - claims should be supported by search results\n"
    "2. Completeness - addresses all aspects of the query\n"
    "3. Coherence - logical flow and clear structure\n"
    "4. Relevance - stays on topic and answers the question\n\n"
    "Be constructive and specific in your feedback."
)


class ReportEvaluation(BaseModel):
    is_acceptable: bool = Field(
        description="Whether the report meets quality standards"
    )
    issues: list[str] = Field(
        description="List of specific issues found (empty if acceptable)"
    )
    suggestions: str = Field(
        description="Specific suggestions for improvement (empty)"
    )
    score: int = Field(description="Quality score from 1-10")


evaluator_agent = Agent(
    name="EvaluatorAgent",
    instructions=INSTRUCTIONS,
    model="gpt-4o-mini",
    output_type=ReportEvaluation,
)
