# Lesson 1.1: System Orchestration (The Boardroom)

## The Concept: The "CEO Approach"
In an institutional system, the entry point (`main.py`) should act like a CEO or a Board of Directors. It should:
1.  Set the **Direction** (What menu option did the user pick?).
2.  Delegate to **Specialists** (Call the Portfolio Manager, the Sync logic, etc.).
3.  Handle **Exceptions** (What if the database is missing?).

It should **NEVER** contain:
- Mathematical formulas (Risk, ATR, etc.).
- SQL queries.
- Raw API calls to brokers.

## Why We Design This Way
- **Auditability:** You can see the high-level logic of your whole business in one 300-line file.
- **Scalability:** If you want to add a "Web Dashboard" next to your "CLI Dashboard," you just create a new orchestrator. The `core/` logic stays the same.

## Deep Dive into `main.py`
Open `main.py` and look for the `main()` function. Notice how it uses a `while True` loop to keep the business running until you say `sys.exit()`.

### Key Code Pattern: The Delegation
```python
if choice == '1':
    handle_manage_positions()
```
`main.py` doesn't know how to manage positions. It imports `handle_manage_positions` from another part of the system.

## Exercise 1
1. Open `main.py`.
2. Find the imports at the top. 
3. Identify which functions are imported from the `core/` directory vs. the `services/` directory.
4. Answer this: Why do we keep `db.py` logic separate from `core/risk_engine.py`?

---
*This is the start of your PE-Grade Systems Course.*
