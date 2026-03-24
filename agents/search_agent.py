import os

from agents import Agent, WebSearchTool, ModelSettings, function_tool

INSTRUCTIONS = (
    "You are a research assistant. Given a search term, you search the web for that term and "
    "produce a concise summary of the results. The summary must 2-3 paragraphs and less than 300 "
    "words. Capture the main points. Write succintly, no need to have complete sentences or good "
    "grammar. This will be consumed by someone synthesizing a report, so its vital you capture the "
    "essence and ignore any fluff. Do not include any additional commentary other than the summary itself."
)

search_agent = Agent(
    name="Search agent",
    instructions=INSTRUCTIONS,
    tools=[WebSearchTool(search_context_size="low")],
    model="gpt-4o-mini",
    model_settings=ModelSettings(tool_choice="required"),
)


@function_tool
def tavily_search(query: str) -> str:
    """Search the web using Tavily and return the results."""
    from tavily import TavilyClient

    client = TavilyClient()
    response = client.search(
        query=query,
        max_results=5,
        search_depth="advanced",
        topic="general",
    )
    results = []
    for r in response["results"]:
        results.append(f"Title: {r['title']}\nURL: {r['url']}\nContent: {r['content']}")
    return "\n\n".join(results)


tavily_search_agent = Agent(
    name="Tavily search agent",
    instructions=INSTRUCTIONS,
    tools=[tavily_search],
    model="gpt-4o-mini",
    model_settings=ModelSettings(tool_choice="required"),
)


def get_search_agent() -> Agent:
    """Return the active search agent based on SEARCH_PROVIDER env var."""
    provider = os.environ.get("SEARCH_PROVIDER", "openai").lower()
    if provider == "tavily":
        return tavily_search_agent
    return search_agent