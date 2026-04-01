import asyncio
import os

from agents import Runner, gen_trace_id, trace
from agents.clarify_agent import ClarifyingQuestion, clarify_agent
from agents.email_agent import email_agent
from agents.evaluator_agent import ReportEvaluation, evaluator_agent
from agents.planner_agent import WebSearchItem, WebSearchPlan, planner_agent
from agents.router_agent import QueryRoute, router_agent
from agents.search_agent import search_agent, tavily_search_agent
from agents.writer_agent import ReportData, writer_agent

MAX_REVISION_ATTEMPTS = 2


class ResearchManager:

    async def run(
        self, 
        query: str, 
        clarifying_answers: list[str] | None = None,
        route_override: str | None = None,
    ):
    
        """Run deep research process, yielding status and final report
        
        Args:
            query: The research query
            clarifying_answers: Optional list of clarifying question answers
            route_override: Optional route override ("quick", "deep", 
                          "technical", "comparative"). If None, uses auto-routing.
        """
        
        trace_id = gen_trace_id()
        with trace("Research trace", trace_id=trace_id):
            trace_url = (
                f"https://platform.openai.com/traces/trace?"
                f"trace_id={trace_id}"
            )
            print(f"View trace: {trace_url}")
            yield f"View trace: {trace_url}"

            # Enrich query if answers provided
            enriched_query = query
            if clarifying_answers:
                enriched_query = self.enrich_query(
                    query, clarifying_answers
                )

            # ROUTING: Determine research approach
            if route_override and route_override != "auto":
                yield f"Using manual route: {route_override}"
                route = await self.route_query(
                    enriched_query, route_override=route_override
                )
                yield f"Route: {route.route} ({route.reasoning})"
            else:
                yield "Analyzing query type (auto-routing)..."
                route = await self.route_query(enriched_query)
                yield f"Route: {route.route} ({route.reasoning})"

            print("Starting research...")
            search_plan = await self.plan_searches(
                enriched_query, route.num_searches
            )
            yield "Searches planned, starting to search..."
            search_results = await self.perform_searches(search_plan)
            yield "Searches complete, writing report..."

            # EVALUATOR-OPTIMIZER: Write report with quality loop
            report = await self.write_report_with_evaluation(
                enriched_query, search_results, route
            )

            yield "Report finalized, sending email..."
            await self.send_email(report)
            yield "Email sent, research complete"
            yield report.markdown_report

    async def route_query(
        self, query: str, route_override: str | None = None
    ) -> QueryRoute:
        """Determine the best research route for the query
        
        Args:
            query: The research query
            route_override: Optional route override. If provided, uses this
                          route instead of auto-routing.
        """
        if route_override:
            # Map route to num_searches
            route_map = {
                "quick": 3,
                "deep": 5,
                "technical": 5,
                "comparative": 6,
            }
            num_searches = route_map.get(route_override, 5)
            return QueryRoute(
                route=route_override,
                reasoning=f"Manually selected {route_override} route",
                num_searches=num_searches,
            )
            
        print("Routing query...")
        result = await Runner.run(
            router_agent,
            f"Query: {query}",
        )
        route = result.final_output_as(QueryRoute)
        print(f"Route selected: {route.route} - {route.reasoning}")
        return route

    async def plan_searches(
        self, query: str, num_searches: int = 5
    ) -> WebSearchPlan:
        """Plan the searches to perform for the query"""
        print(f"Planning {num_searches} searches...")
        result = await Runner.run(
            planner_agent,
            f"Query: {query}\nNumber of searches to plan: {num_searches}",
        )
        print(f"Will perform {len(result.final_output.searches)} searches")
        return result.final_output_as(WebSearchPlan)

    async def generate_clarifying_question(
        self, query: str, qa_history: list[tuple[str, str]]
    ) -> ClarifyingQuestion:
        """Generate clarifying question based on query and Q&A history"""
        print("Generating clarifying question...")

        # Build context with previous Q&A
        context = f"Original research query: {query}\n\n"
        if qa_history:
            context += "Previous clarifying questions and answers:\n"
            for i, (q, a) in enumerate(qa_history, 1):
                context += f"{i}. Q: {q}\n   A: {a}\n\n"
        context += (
            "Generate the next clarifying question to better "
            "understand the user's needs."
        )

        result = await Runner.run(
            clarify_agent,
            context,
        )
        return result.final_output_as(ClarifyingQuestion)

    def enrich_query(
        self, original_query: str, qa_pairs: list[tuple[str, str]]
    ) -> str:
        """Combine original query with Q&A pairs into enriched context"""
        if not qa_pairs or all(not answer.strip()
                               for _, answer in qa_pairs):
            return original_query

        enriched = (
            f"Original Query: {original_query}\n\nAdditional Context:\n"
        )
        for question, answer in qa_pairs:
            if answer.strip():
                enriched += f"- {question}\n  Answer: {answer}\n"
        return enriched

    async def perform_searches(
        self, search_plan: WebSearchPlan
    ) -> list[str]:
        """Perform the searches to perform for the query"""
        print("Searching...")
        num_completed = 0
        tasks = [
            asyncio.create_task(self.search(item))
            for item in search_plan.searches
        ]
        results = []
        for task in asyncio.as_completed(tasks):
            result = await task
            if result is not None:
                results.append(result)
            num_completed += 1
            print(f"Searching... {num_completed}/{len(tasks)} completed")
        print("Finished searching")
        return results

    async def search(self, item: WebSearchItem) -> str | None:
        """Perform a search for the query"""
        provider = os.environ.get("SEARCH_PROVIDER", "openai").lower()
        agent = tavily_search_agent if provider == "tavily" else search_agent
        search_input = (
            f"Search term: {item.query}\n"
            f"Reason for searching: {item.reason}"
        )
        try:
            result = await Runner.run(
                agent,
                search_input,
            )
            return str(result.final_output)
        except Exception:
            return None

    async def write_report(
        self, query: str, search_results: list[str], feedback: str = ""
    ) -> ReportData:
        """Write the report for the query"""
        print("Writing report...")
        report_input = (
            f"Original query: {query}\n"
            f"Summarized search results: {search_results}"
        )
        if feedback:
            report_input += (
                f"\n\nPrevious attempt feedback:\n{feedback}\n\n"
                "Please address these issues in your revised report."
            )

        result = await Runner.run(
            writer_agent,
            report_input,
        )
        return result.final_output_as(ReportData)

    async def evaluate_report(
        self, query: str, report: ReportData, search_results: list[str]
    ) -> ReportEvaluation:
        """Evaluate report quality"""
        print("Evaluating report quality...")
        eval_input = (
            f"Query: {query}\n\n"
            f"Report:\n{report.markdown_report}\n\n"
            f"Search results used:\n{search_results[:3]}"
        )
        result = await Runner.run(
            evaluator_agent,
            eval_input,
        )
        evaluation = result.final_output_as(ReportEvaluation)
        status = '✓ Acceptable' if evaluation.is_acceptable else (
            '✗ Needs revision'
        )
        print(f"Evaluation: {status} (Score: {evaluation.score}/10)")
        return evaluation

    async def write_report_with_evaluation(
        self, query: str, search_results: list[str], route: QueryRoute
    ) -> ReportData:
        """Write report with quality evaluation and revision loop"""
        attempt = 0
        feedback = ""

        while attempt < MAX_REVISION_ATTEMPTS:
            attempt += 1

            # Write report
            report = await self.write_report(
                query, search_results, feedback
            )

            # Evaluate (skip for quick queries to save cost)
            if route.route == "quick" or attempt >= MAX_REVISION_ATTEMPTS:
                print(f"Report complete (attempt {attempt})")
                return report

            evaluation = await self.evaluate_report(
                query, report, search_results
            )

            if evaluation.is_acceptable:
                print(f"✓ Report approved on attempt {attempt}")
                return report

            # Prepare feedback for revision
            feedback = (
                f"Issues: {', '.join(evaluation.issues)}\n"
                f"Suggestions: {evaluation.suggestions}"
            )
            print(
                f"Revision needed "
                f"(attempt {attempt}/{MAX_REVISION_ATTEMPTS})"
            )

        print("Max revisions reached, returning final report")
        return report

    async def send_email(self, report: ReportData) -> None:
        print("Writing email...")
        await Runner.run(
            email_agent,
            report.markdown_report,
        )
        print("Email sent")
