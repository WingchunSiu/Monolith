"""
Test RLM for dataset curation: cleaning, fixing, and augmenting a dirty dataset.

This creates a small intentionally messy dataset and asks the RLM to:
1. Profile data quality issues
2. Fix typos and inconsistencies
3. Fill missing fields using sub-LLM classification
4. Generate synthetic examples for underrepresented categories
5. Return the cleaned dataset

Usage:
    export OPENAI_API_KEY="sk-..."
    python test_dataset_curation.py
"""
from rlm.rlm_repl import RLM_REPL
import json
import os

# Intentionally dirty dataset with known issues
DIRTY_DATASET = [
    # Good rows
    {"text": "The Eiffel Tower is located in Paris, France", "label": "geography", "source": "textbook"},
    {"text": "Photosynthesis converts sunlight into chemical energy", "label": "science", "source": "wiki"},
    {"text": "The quadratic formula solves ax^2 + bx + c = 0", "label": "math", "source": "textbook"},

    # Typos in text
    {"text": "The cpaital of Germany is Berln", "label": "geography", "source": "user"},
    {"text": "Einsten developed the theroy of relativty", "label": "science", "source": "user"},
    {"text": "Pythonn is a populer programing langauge", "label": "technology", "source": "user"},

    # Missing labels
    {"text": "Mount Everest is the tallest mountain on Earth", "label": "", "source": "wiki"},
    {"text": "Machine learning is a subset of artificial intelligence", "label": "", "source": "article"},
    {"text": "The Fibonacci sequence starts with 0, 1, 1, 2, 3, 5", "label": "", "source": "textbook"},

    # Inconsistent label casing
    {"text": "Water boils at 100 degrees Celsius", "label": "SCIENCE", "source": "textbook"},
    {"text": "Tokyo is the capital of Japan", "label": "Geography", "source": "wiki"},
    {"text": "Pi is approximately 3.14159", "label": "MATH", "source": "textbook"},

    # Missing text (should be flagged/removed)
    {"text": "", "label": "science", "source": "unknown"},
    {"text": None, "label": "math", "source": "unknown"},

    # Duplicate-ish rows
    {"text": "The Eiffel Tower is in Paris, France", "label": "geography", "source": "blog"},

    # Missing source
    {"text": "Gravity pulls objects toward each other", "label": "science", "source": ""},
    {"text": "HTML is a markup language for web pages", "label": "technology", "source": None},
]


def main():
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("ERROR: Set OPENAI_API_KEY environment variable first.")
        print("  export OPENAI_API_KEY='sk-...'")
        return

    print("=== RLM Dataset Curation Test ===\n")
    print(f"Input: {len(DIRTY_DATASET)} rows with known issues\n")

    rlm = RLM_REPL(
        model="gpt-4o-mini",
        recursive_model="gpt-4o-mini",
        enable_logging=True,
        max_iterations=15,
    )

    query = """You are a dataset curation specialist. Analyze this JSON dataset and perform these tasks:

1. PROFILE: Count and categorize all data quality issues (missing values, typos, inconsistent casing, near-duplicates, null values)
2. CLEAN:
   - Fix typos in the "text" field using llm_query() for each problematic row
   - Normalize all labels to lowercase
   - Fill missing labels by classifying the text using llm_query()
   - Remove or flag rows with empty/null text
   - Fill missing "source" values with "unknown"
3. AUGMENT:
   - Check category distribution
   - For any category with fewer than 3 clean examples, generate 1-2 synthetic rows using llm_query()
4. VALIDATE: Print a summary of changes made
5. Return the final cleaned + augmented dataset as a JSON array using FINAL_VAR

Important: Use llm_query() for semantic tasks (fixing typos, classifying, generating). Use Python code for structural tasks (parsing, counting, filtering)."""

    context = json.dumps(DIRTY_DATASET, indent=2)

    print(f"Query: {query[:200]}...\n")
    result = rlm.completion(context=context, query=query)

    print(f"\n{'='*60}")
    print("=== CURATION RESULT ===")
    print(f"{'='*60}\n")

    # Try to parse result as JSON for nice display
    try:
        cleaned = json.loads(result)
        print(f"Output: {len(cleaned)} rows")
        print(json.dumps(cleaned, indent=2))
    except (json.JSONDecodeError, TypeError):
        print(result)


if __name__ == "__main__":
    main()
