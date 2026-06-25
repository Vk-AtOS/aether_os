"""
Benchmark DCSP repair accuracy against known bugs.
Runs the repair pipeline against curated test cases and reports accuracy per error type.
"""

import sys
import os
import json
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.dfle.log_parser import parse_log
from src.slm.prompt_templates import PromptTemplates
from src.slm.patch_validator import PatchValidator
from src.slm.ollama_client import OllamaClient

TEST_CASES = [
    {
        "name": "ConnectionTimeout",
        "log_file": "tests/fixtures/ci_logs/connection_timeout.log",
        "source_file": "tests/fixtures/repos/python_bugs/connection_timeout.py",
        "error_type": "ConnectionTimeout",
        "expected_keywords": ["retry", "except", "Timeout"],
    },
    {
        "name": "NullPointer/AttributeError",
        "log_file": "tests/fixtures/ci_logs/null_pointer.log",
        "source_file": "tests/fixtures/repos/python_bugs/null_pointer.py",
        "error_type": "AttributeError",
        "expected_keywords": ["None", "if", "get("],
    },
    {
        "name": "ImportError",
        "log_file": "tests/fixtures/ci_logs/import_error.log",
        "source_file": "tests/fixtures/repos/python_bugs/import_error.py",
        "error_type": "ImportError",
        "expected_keywords": ["try", "except", "ImportError"],
    },
]

def run_benchmark():
    client = OllamaClient()
    validator = PatchValidator()
    results = []

    print("DCSP Repair Benchmark")
    print("=" * 50)

    if not client.is_available():
        print("ERROR: Ollama service not available. Start it before running benchmark.")
        return 0

    for case in TEST_CASES:
        print(f"Testing: {case['name']}...")
        try:
            log_path = Path(case["log_file"])
            source_path = Path(case["source_file"])
            
            if not log_path.exists() or not source_path.exists():
                result = f"ERROR: Fixture files missing for {case['name']}"
                score = 0
            else:
                log = log_path.read_text()
                source = source_path.read_text()
                filename = source_path.name

                system, user = PromptTemplates.build_prompt(
                    case["error_type"], log, source, filename
                )

                response = client.generate_patch(system, user)

                if response is None:
                    result = "FAIL: No valid diff generated"
                    score = 0
                else:
                    diff = validator.extract_diff(response)
                    if diff is None:
                        result = "FAIL: Could not extract diff"
                        score = 0
                    elif not validator.is_valid_diff(diff):
                        result = "FAIL: Invalid diff format"
                        score = 0
                    else:
                        keywords_found = sum(1 for kw in case["expected_keywords"] if kw in diff)
                        score = keywords_found / len(case["expected_keywords"])
                        result = (f"PASS (score: {score:.0%}, keywords: "
                                  f"{keywords_found}/{len(case['expected_keywords'])})")
        except Exception as e:
            result = f"ERROR: {e}"
            score = 0

        results.append({
            "name": case["name"],
            "result": result,
            "score": score
        })
        print(f"  {result}")

    avg = sum(r["score"] for r in results) / len(results) if results else 0
    print("=" * 50)
    print(f"Overall accuracy: {avg:.0%}")
    print(f"Cases tested: {len(results)}")

    # Save results
    Path("benchmark_results.json").write_text(json.dumps(results, indent=2))
    print("Results saved to benchmark_results.json")
    return avg

if __name__ == "__main__":
    run_benchmark()
