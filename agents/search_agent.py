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


# --- Tavily-backed search agent (additive, selected via SEARCH_PROVIDER env var) ---

@function_tool
async def tavily_search_tool(query: str) -> str:
    """Search the web using Tavily and return a summary of results."""
    from tavily import AsyncTavilyClient

    client = AsyncTavilyClient(api_key=os.environ["TAVILY_API_KEY"])
    response = await client.search(
        query=query,
        max_results=5,
        search_depth="advanced",
        topic="general",
    )
    parts = []
    for result in response["results"]:
        title = result.get("title", "")
        content = result.get("content", "")
        parts.append(f"{title}: {content}")
    return "\n\n".join(parts)


tavily_search_agent = Agent(
    name="Tavily search agent",
    instructions=INSTRUCTIONS,
    tools=[tavily_search_tool],
    model="gpt-4o-mini",
    model_settings=ModelSettings(tool_choice="required"),
)