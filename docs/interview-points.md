# Interview points

Short, honest talking points for Jagadish-deep-agents. Every number quoted is from the
real run shown in the README.

- Plans are data before they are actions, which makes them inspectable and testable.
- Recovery order matters: cheap retry first, abort last, all within a budget.
- In the demo, memory removes the replanning on the second run entirely.
- Known gap: lessons never expire.

## Likely follow-up questions

- How do you stop a bad lesson spreading? (Expiry, confidence counts and a cap on how many lessons apply.)
- Why not let the LLM loop freely? (Cost and safety; a bounded plan is auditable.)
- How would you test an LLM planner? (Golden goals with expected plan shapes, plus failure injection.)
