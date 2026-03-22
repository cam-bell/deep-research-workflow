# app.py - Entry point for HuggingFace Spaces
from agents.deep_research_interactive import ui

# Launch without opening browser (HF handles this)
ui.launch(server_name="0.0.0.0", server_port=7860)
