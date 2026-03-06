"""
Demo script showcasing EVALUATOR-OPTIMIZER and ROUTING patterns

Run with: python demo_patterns.py
"""
import asyncio
from dotenv import load_dotenv
from research_manager import ResearchManager

load_dotenv(override=True)


async def demo_routing():
    """Demonstrate how different queries get routed to different workflows"""
    print("=" * 60)
    print("DEMO: ROUTING PATTERN")
    print("=" * 60)
    print()

    queries = [
        ("What is the capital of France?", "quick"),
        ("Explain quantum entanglement in physics", "technical"),
        ("Compare Python vs JavaScript for web development", "comparative"),
        ("What are the long-term implications of AI on employment?", "deep"),
    ]

    manager = ResearchManager()

    for query, expected_route in queries:
        print(f"Query: {query}")
        print(f"Expected route: {expected_route}")

        route = await manager.route_query(query)
        print(f"Actual route: {route.route}")
        print(f"Reasoning: {route.reasoning}")
        print(f"Searches planned: {route.num_searches}")
        print("-" * 60)
        print()


async def demo_evaluation():
    """Demonstrate the evaluator-optimizer pattern"""
    print("=" * 60)
    print("DEMO: EVALUATOR-OPTIMIZER PATTERN")
    print("=" * 60)
    print()

    # Note: This would require actual search results
    # For demo purposes, we'll just show the structure
    print("The evaluation loop works as follows:")
    print()
    print("1. Writer Agent creates initial report")
    print("2. Evaluator Agent reviews for:")
    print("   - Accuracy (claims supported by sources)")
    print("   - Completeness (addresses all aspects)")
    print("   - Coherence (logical flow)")
    print("   - Relevance (stays on topic)")
    print()
    print("3. If score < acceptable threshold:")
    print("   → Provides specific feedback")
    print("   → Writer revises with feedback")
    print("   → Loop repeats (max 2 revisions)")
    print()
    print("4. If score ≥ acceptable threshold:")
    print("   → Report approved ✓")
    print("   → Proceeds to email delivery")
    print()


async def demo_full_workflow():
    """
    Demonstrate complete workflow with both patterns
    (Commented out to avoid actual API calls)
    """
    print("=" * 60)
    print("DEMO: FULL WORKFLOW")
    print("=" * 60)
    print()

    query = "What are the latest developments in quantum computing?"

    print(f"Query: {query}")
    print()
    print("Workflow steps:")
    print("1. ROUTING: Query analyzed and classified")
    print("2. PLANNING: Searches planned based on route")
    print("3. PARALLELIZATION: Multiple searches execute concurrently")
    print("4. WRITING: Initial report generated")
    print("5. EVALUATION: Report quality assessed")
    print("6. OPTIMIZATION: Revisions if needed (with feedback)")
    print("7. FINALIZATION: Report approved and sent")
    print()
    print("To run actual research, use:")
    print("  python deep_research.py")
    print("  OR")
    print("  python deep_research_interactive.py")
    print()

    # Uncomment to run actual research:
    # manager = ResearchManager()
    # async for status in manager.run(query):
    #     print(status)


async def main():
    """Run all demos"""
    await demo_routing()
    print("\n" + "=" * 60 + "\n")
    await demo_evaluation()
    print("\n" + "=" * 60 + "\n")
    await demo_full_workflow()


if __name__ == "__main__":
    print("\n🔬 Agentic Workflow Patterns Demo\n")
    asyncio.run(main())
    print("\n✅ Demo complete!\n")
