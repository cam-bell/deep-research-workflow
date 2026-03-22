import gradio as gr
from dotenv import load_dotenv

from agents.research_manager import ResearchManager

load_dotenv(override=True)

MAX_QUESTIONS = 3


async def reset_research():
    """Reset all state to start a new research session"""
    return (
        "",  # Clear conversation display
        gr.update(visible=False),  # Hide answer section
        gr.update(visible=False),  # Hide submit button
        [],  # Clear QA history
        "",  # Clear query state
        gr.update(visible=False),  # Hide reset button
        "auto", #Reset route mode to auto
    )


async def start_clarification(
    query: str, qa_history: list, route_mode: str
):
    """Step 1: Start the clarification process by generating first question"""
    if not query.strip():
        return (
            "❌ Please enter a research query first.",
            gr.update(visible=False),
            gr.update(visible=False),
            qa_history,
            query,
            gr.update(visible=False),  # Reset button
            route_mode, # Keep route mode
        )

    manager = ResearchManager()

    # Generate first question
    question_obj = await manager.generate_clarifying_question(query, [])

    # Format for display
    route_info = (
        f"*Research mode: {route_mode}*"
        if route_mode != "auto"
        else "*Research mode: Auto (AI will choose best approach)*"
    )
    question_md = f"## 🤔 Clarifying Question 1 of {MAX_QUESTIONS}\n\n"
    question_md += f"{route_info}\n\n"
    question_md += f"**{question_obj.question}**\n\n"
    question_md += f"*Why we're asking: {question_obj.why_asking}*\n\n"
    question_md += "Please provide your answer below (or leave blank to skip):"

    return (
        question_md,
        gr.update(visible=True),  # Show answer section
        gr.update(visible=True),  # Show submit button
        [(question_obj.question, "")],  # Initialize QA history
        query,  # Store original query
        gr.update(visible=False),  # Hide reset button during Q&A
        route_mode,  # Store route mode
    )


async def handle_answer(query: str, answer: str, qa_history: list, route_mode: str):
    """Handle user's answer and either ask next question or start research"""
    if not qa_history:
        yield (
            "Error: No question in progress",
            gr.update(),
            gr.update(),
            qa_history,
            "",
            gr.update(visible=False),
            route_mode,
        )
        return

    # Update the last question with the answer
    qa_history[-1] = (qa_history[-1][0], answer.strip())

    manager = ResearchManager()

    # Check if we've asked 3 questions
    if len(qa_history) >= MAX_QUESTIONS:
        # Time to start research!
        route_display = (
            f" ({route_mode} mode)"
            if route_mode != "auto"
            else " (auto-routing)"
        )
        yield (
            f"✅ All {MAX_QUESTIONS} questions answered! "
            f"Starting research{route_display}...",
            gr.update(visible=False),
            gr.update(visible=False),
            qa_history,
            "",
            gr.update(visible=False),  # Hide reset during research
            route_mode,
        )

        # Create enriched query and run research
        enriched_query = manager.enrich_query(query, qa_history)

        # Convert "auto" to None for the manager
        route_override = None if route_mode == "auto" else route_mode
        
        final_chunk = ""
        async for chunk in manager.run(enriched_query, route_override=route_override):
            final_chunk = chunk
            yield (
                chunk,
                gr.update(visible=False),
                gr.update(visible=False),
                qa_history,
                "",
                gr.update(visible=False),
                route_mode,
            )

        # Show reset button after completion
        completion_text = (
            f"{final_chunk}\n\n---\n\n"
            "✅ **Research Complete!** "
            "Click 'Start New Research' to begin again."
        )
        yield (
            completion_text,
            gr.update(visible=False),
            gr.update(visible=False),
            qa_history,
            "",
            gr.update(visible=True),  # Show reset button
            route_mode,
        )
        return

    # Generate next question
    question_num = len(qa_history) + 1
    question_obj = await manager.generate_clarifying_question(
        query, qa_history
    )

    # Add new question to history
    qa_history.append((question_obj.question, ""))

    # Format for display
    question_md = (
        f"## 🤔 Clarifying Question {question_num} "
        f"of {MAX_QUESTIONS}\n\n"
    )

    # Show previous Q&A
    question_md += "### Previous answers:\n"
    for i, (q, a) in enumerate(qa_history[:-1], 1):
        question_md += f"{i}. **{q}**\n"
        if a:
            question_md += f"   ✓ {a}\n\n"
        else:
            question_md += "   *(skipped)*\n\n"

    question_md += "---\n\n"
    question_md += f"**{question_obj.question}**\n\n"
    question_md += f"*Why we're asking: {question_obj.why_asking}*\n\n"
    question_md += (
        "Please provide your answer below (or leave blank to skip):"
    )

    yield (
        question_md,
        gr.update(visible=True, value=""),  # Clear answer box
        gr.update(visible=True),
        qa_history,
        query,
        gr.update(visible=False),  # Keep reset hidden during Q&A
        route_mode,
    )

# Build UI
with gr.Blocks() as ui:
    gr.Markdown("# 🔬 Deep Research (with Sequential Clarifying Questions)")
    gr.Markdown("*Ask questions one at a time, building context as we go*")

    # Hidden state
    qa_history_state = gr.State([])
    query_state = gr.State("")
    route_mode_state = gr.State("auto")

    with gr.Row():
        query_textbox = gr.Textbox(
            label="What topic would you like to research?",
            placeholder=(
                "e.g., What are the most exciting commercial "
                "applications of Autonomous Agentic AI?"
            ),
            lines=3
        )
    with gr.Row():
        route_radio = gr.Radio(
            label="Research Mode",
            choices=[
                ("Auto (Recommended)", "auto"),
                ("Quick (3 searches)", "quick"),
                ("Deep (5 searches)", "deep"),
                ("Technical (5 searches)", "technical"),
                ("Comparative (6 searches)", "comparative"),
            ],
            value="auto",
            info=(
                "Auto mode uses AI to select the best approach. "
                "Manual modes let you control the research depth."
            ),
        )

    with gr.Row():
        start_btn = gr.Button(
            "🚀 Start Research with Clarifying Questions",
            variant="primary",
            size="lg"
        )
        reset_btn = gr.Button(
            "🔄 Start New Research",
            variant="secondary",
            size="lg",
            visible=False
        )

    conversation_display = gr.Markdown(
        label="Conversation", visible=True
    )

    with gr.Column(visible=False) as answer_section:
        answer_box = gr.Textbox(
            label="Your Answer",
            placeholder="Type your answer here, or leave blank to skip...",
            lines=3
        )
        submit_btn = gr.Button(
            "Submit Answer & Continue", variant="primary"
        )

    # Wire up events
    start_btn.click(
        fn=start_clarification,
        inputs=[query_textbox, qa_history_state, route_radio],
        outputs=[
            conversation_display,
            answer_section,
            submit_btn,
            qa_history_state,
            query_state,
            reset_btn,
            route_mode_state,
        ]
    )

    # Update route mode when radio changes
    route_radio.change(
        fn=lambda x: x,
        inputs=[route_radio],
        outputs=[route_mode_state],
    )

    reset_btn.click(
        fn=reset_research,
        inputs=[],
        outputs=[
            conversation_display,
            answer_section,
            submit_btn,
            qa_history_state,
            query_state,
            reset_btn,
            route_mode_state,
        ]
    )

    submit_btn.click(
        fn=handle_answer,
        inputs=[query_state, answer_box, qa_history_state, route_mode_state],
        outputs=[
            conversation_display,
            answer_section,
            submit_btn,
            qa_history_state,
            answer_box,
            reset_btn,
            route_mode_state,
        ]
    )

    # Allow Enter key to submit
    answer_box.submit(
        fn=handle_answer,
        inputs=[query_state, answer_box, route_mode_state],
        outputs=[
            conversation_display,
            answer_section,
            submit_btn,
            qa_history_state,
            answer_box,
            reset_btn,
            route_mode_state,
        ]
    )

ui.launch(inbrowser=True)
