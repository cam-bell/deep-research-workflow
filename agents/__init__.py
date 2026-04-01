from __future__ import annotations

import importlib.machinery
import importlib.util
import sys
from pathlib import Path


def _load_sdk_module():
    package_dir = Path(__file__).resolve().parent
    project_root = package_dir.parent.resolve()
    search_paths: list[str] = []

    for entry in sys.path:
        resolved = Path(entry or ".").resolve()
        if resolved != project_root:
            search_paths.append(str(resolved))

    spec = importlib.machinery.PathFinder.find_spec(__name__, search_paths)
    if spec is None or spec.loader is None:
        raise ImportError("Could not locate the external 'agents' package")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_sdk = _load_sdk_module()

Agent = _sdk.Agent
Runner = _sdk.Runner
ModelSettings = _sdk.ModelSettings
WebSearchTool = _sdk.WebSearchTool
function_tool = _sdk.function_tool
gen_trace_id = _sdk.gen_trace_id
trace = _sdk.trace

from agents.search_agent import tavily_search_agent
from agents.research_manager import ResearchManager
