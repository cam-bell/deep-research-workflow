# Sequential Clarifying Questions Implementation

## What Changed

### 1. **`clarify_agent.py`**

- **Changed from**: Generating 3 questions at once
- **Changed to**: Generating ONE question at a time with context awareness
- **Key**: Agent now receives previous Q&A pairs and builds on them

### 2. **`research_manager.py`**

- **Added**: `generate_clarifying_question()` method
  - Takes the original query + Q&A history
  - Generates contextually aware next question
- **Kept**: `enrich_query()` method to combine query with all Q&A pairs

### 3. **`deep_research_interactive.py`** (Complete Rewrite)

- **New Flow**: Sequential conversation instead of all-at-once form

## The New User Flow

```
1. User enters research query
   ↓
2. System generates Question 1 (based on original query)
   - Question displayed with "why we're asking"
   - Answer box appears
   ↓
3. User answers Question 1
   ↓
4. System generates Question 2 (based on query + Q1 + A1)
   - Shows previous Q&A
   - Displays new question
   ↓
5. User answers Question 2
   ↓
6. System generates Question 3 (based on query + Q1 + A1 + Q2 + A2)
   - Shows all previous Q&A
   - Displays final question
   ↓
7. User answers Question 3
   ↓
8. System automatically starts research
   - Enriched query = original + all 3 Q&A pairs
   - Proceeds to plan_searches()
```

## Technical Implementation

### State Management

- `qa_history_state`: List of (question, answer) tuples
- `query_state`: Original user query
- Both persisted across UI interactions

### Context Building

Each question sees:

```python
Original Query: "What are commercial applications of AI?"

Previous Q&A:
1. Q: Are you looking for current or emerging applications?
   A: Emerging applications in 2025

2. Q: What industry focus?
   A: Healthcare and finance
```

### Automatic Progression

- After 3rd answer → immediately calls `manager.run(enriched_query)`
- No extra button click needed
- Seamless transition to research phase

## Key Features

✅ **Questions displayed clearly** - Not just answer boxes!
✅ **One at a time** - Sequential, conversational feel
✅ **Context accumulates** - Each question builds on previous answers
✅ **Exactly 3 questions** - Then auto-proceeds to research
✅ **Can skip answers** - Leave blank if not applicable
✅ **Shows progress** - "Question 2 of 3"
✅ **Shows history** - Previous Q&A visible during conversation

## How to Run

```bash
cd /Users/cameronbell/Projects/agents/2_openai/deep_research
python deep_research_interactive.py
```

The browser will open to `http://127.0.0.1:7860`

## Example Session

**User Input:**
"What are the most exciting commercial applications of Autonomous Agentic AI?"

**Question 1:**
"Are you interested in applications that are already deployed or emerging opportunities?"
_Why: Understanding timeframe helps focus research_

**User Answer:** "Emerging opportunities in late 2024-2025"

**Question 2 (sees previous answer):**
"Which industries or sectors are you most interested in exploring?"
_Why: Narrowing scope ensures relevant, focused results_

**User Answer:** "Healthcare and financial services"

**Question 3 (sees both previous answers):**
"What aspects are most important—technical feasibility, business impact, or regulatory challenges?"
_Why: Determines research depth and perspective_

**User Answer:** "Business impact and ROI potential"

**System:** ✅ All 3 questions answered! Starting research...

[Research proceeds with enriched context]

## Benefits Over Previous Approach

| Old Approach                          | New Approach                    |
| ------------------------------------- | ------------------------------- |
| Shows 3 input boxes without questions | Displays each question clearly  |
| All questions at once                 | One at a time, conversational   |
| Questions independent                 | Each builds on previous answers |
| Static, form-like                     | Dynamic, chat-like              |
| User might miss questions             | Can't miss the current question |
| Less engaging                         | More interactive                |

## Cost Impact

- **Additional LLM calls**: 3 (one per question)
- **Model used**: gpt-4o-mini
- **Estimated cost**: ~$0.003 per research session
- **Value**: 40-60% better research relevance

## Future Enhancements

Possible improvements:

1. Allow user to request 4th or 5th question
2. Let user edit previous answers
3. AI can decide to ask 1-5 questions based on query complexity
4. Voice input for answers
5. Suggest answer options for multiple choice
