from pydantic import BaseModel, Field
from agents import Agent

INSTRUCTIONS = (
    "You are a helpful research assistant. "
    "Given a query and the requested number of searches, "
    "come up with a set of web searches to perform to best answer "
    "the query. Create diverse, specific search terms that cover "
    "different aspects of the topic."
)


class WebSearchItem(BaseModel):
    reason: str = Field(
        description="Your reasoning for why this search is important."
    )
    query: str = Field(
        description="The search term to use for the web search."
    )


class WebSearchPlan(BaseModel):
    searches: list[WebSearchItem] = Field(
        description="A list of web searches to perform to answer the query."
    )


planner_agent = Agent(
    name="PlannerAgent",
    instructions=INSTRUCTIONS,
    model="gpt-4o-mini",
    output_type=WebSearchPlan,
)
