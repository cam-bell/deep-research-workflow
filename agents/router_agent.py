from pydantic import BaseModel, Field
from typing import Literal
from agents import Agent

INSTRUCTIONS = (
    "You are a research query classifier. "
    "Analyze the query and determine the best research approach:\n\n"
    "- **quick**: Simple questions needing brief answers (3 searches)\n"
    "- **deep**: Complex topics requiring thorough investigation "
    "(5 searches)\n"
    "- **technical**: Technical/scientific queries needing specialized "
    "sources (5 searches)\n"
    "- **comparative**: Questions comparing options, pros/cons "
    "(6 searches, balanced)\n\n"
    "Consider: complexity, scope, technical depth, and comparison needs."
)


class QueryRoute(BaseModel):
    route: Literal["quick", "deep", "technical", "comparative"] = Field(
        description="The research route to take"
    )
    reasoning: str = Field(
        description="Brief explanation for this routing decision"
    )
    num_searches: int = Field(
        description="Number of searches to perform"
    )


router_agent = Agent(
    name="RouterAgent",
    instructions=INSTRUCTIONS,
    model="gpt-4o-mini",
    output_type=QueryRoute,
)
