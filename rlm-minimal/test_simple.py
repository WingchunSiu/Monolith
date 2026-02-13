"""
Simple test for RLM-Minimal: A small task to verify everything works
before running the full needle-in-haystack example.

Usage:
    export OPENAI_API_KEY="sk-..."
    python test_simple.py
"""
from rlm.rlm_repl import RLM_REPL
import os

def main():
    # Check API key
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("ERROR: Set OPENAI_API_KEY environment variable first.")
        print("  export OPENAI_API_KEY='sk-...'")
        return

    print("=== RLM-Minimal: Simple Test ===\n")

    # Use cheaper models for testing
    rlm = RLM_REPL(
        model="gpt-4o-mini",
        recursive_model="gpt-4o-mini",
        enable_logging=True,
        max_iterations=5,
    )

    # Small context — a CSV dataset with a question
    context = """Name,Department,Salary,YearsExp
Alice,Engineering,95000,5
Bob,Marketing,72000,3
Charlie,Engineering,110000,8
Diana,Sales,68000,2
Eve,Engineering,105000,7
Frank,Marketing,78000,4
Grace,Sales,71000,3
Hank,Engineering,125000,12
Ivy,Sales,65000,1
Jack,Marketing,82000,6"""

    query = "What is the average salary per department? Which department has the highest average? List the top 3 earners."

    print(f"Query: {query}\n")
    result = rlm.completion(context=context, query=query)
    print(f"\n=== RESULT ===\n{result}")


if __name__ == "__main__":
    main()
