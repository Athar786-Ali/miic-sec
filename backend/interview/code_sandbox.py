"""
MIIC-Sec — Code Sandbox
Static analysis (Bandit) + Docker-isolated execution for candidate code.

IMPORTANT: Docker must be running on the host machine.
           On M1 Mac, use Docker Desktop with Rosetta / native ARM images.
"""

import json
import os
import subprocess
import tempfile
import time
from typing import List

# ─── Security keywords for basic static checks ───────────────────
DANGEROUS_PATTERNS = [
    ("eval(", "Use of eval() is forbidden"),
    ("exec(", "Use of exec() is forbidden"),
    ("__import__", "Dynamic __import__ is forbidden"),
    ("os.system(", "os.system() calls are not allowed"),
    ("subprocess.call(", "Bare subprocess.call() is not allowed"),
    ("subprocess.Popen(", "Bare subprocess.Popen() is not allowed"),
]


# ═══════════════════════════════════════════════════════════════════
# 1. run_static_analysis
# ═══════════════════════════════════════════════════════════════════

def run_static_analysis(code: str, language: str) -> List[dict]:
    """
    Perform static security analysis on submitted code.

    For Python:
        - Runs ``bandit`` with JSON output on a temporary file.
        - Also applies the universal dangerous-pattern checks below.

    For all languages:
        - Scans for common dangerous patterns (eval, exec, os.system, …).

    Args:
        code:     Source code string submitted by the candidate.
        language: Programming language identifier ("python", "javascript", …).

    Returns:
        List of issue dicts: [{"severity": str, "message": str}]
        Empty list means no issues found.
    """
    issues: List[dict] = []

    # ── Universal dangerous-pattern scan ─────────────────────────
    for pattern, message in DANGEROUS_PATTERNS:
        if pattern in code:
            issues.append({"severity": "HIGH", "message": message})

    # ── Python-specific: Bandit ───────────────────────────────────
    if language.lower() == "python":
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                suffix=".py",
                prefix="miic_bandit_",
                delete=False,
            ) as tmp:
                tmp.write(code)
                tmp_path = tmp.name

            result = subprocess.run(
                ["bandit", "-r", "-f", "json", tmp_path],
                capture_output=True,
                text=True,
                timeout=30,
            )

            try:
                report = json.loads(result.stdout)
                for entry in report.get("results", []):
                    issues.append(
                        {
                            "severity": entry.get("issue_severity", "MEDIUM"),
                            "message": entry.get("issue_text", "Unknown issue"),
                        }
                    )
            except json.JSONDecodeError:
                # Bandit may produce no JSON output if the file is empty
                pass

        except FileNotFoundError:
            # bandit not installed — skip but log warning
            print("⚠️  bandit not found; skipping Bandit static analysis")
        except subprocess.TimeoutExpired:
            issues.append({"severity": "MEDIUM", "message": "Static analysis timed out"})
        except Exception as exc:
            print(f"⚠️  Bandit error: {exc}")
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

    return issues


# ═══════════════════════════════════════════════════════════════════
# 2. execute_in_sandbox
# ═══════════════════════════════════════════════════════════════════

def execute_in_sandbox(code: str, language: str, session_id: str) -> dict:
    """
    Execute code inside a restricted Docker container.

    Container limits:
        --network none   (no outbound access)
        --memory 128m    (hard memory cap)
        --cpus 0.5       (CPU throttle)
        --read-only      (read-only root filesystem)

    Args:
        code:       Source code to execute.
        language:   "python" (only Python is supported in v1).
        session_id: Used to name the temp file uniquely.

    Returns:
        {
            "stdout":             str,
            "stderr":             str,
            "execution_time_ms":  float,
            "timed_out":          bool,
            "exit_code":          int
        }
    """
    tmp_path = f"/tmp/miic_sandbox_{session_id}.py"

    # Write code to host temp file (mounted read-only into container)
    try:
        with open(tmp_path, "w") as f:
            f.write(code)
    except OSError as exc:
        return {
            "stdout": "",
            "stderr": f"Failed to write temp file: {exc}",
            "execution_time_ms": 0.0,
            "timed_out": False,
            "exit_code": -1,
        }

    docker_cmd = [
        "docker", "run", "--rm",
        "--network", "none",
        "--memory", "128m",
        "--cpus", "0.5",
        "--read-only",
        "-v", f"{tmp_path}:/code/solution.py:ro",
        "python:3.11-slim",
        "python", "/code/solution.py",
    ]

    stdout = ""
    stderr = ""
    exit_code = -1
    timed_out = False
    start = time.perf_counter()

    try:
        proc = subprocess.run(
            docker_cmd,
            capture_output=True,
            text=True,
            timeout=10,
        )
        stdout = proc.stdout
        stderr = proc.stderr
        exit_code = proc.returncode
    except subprocess.TimeoutExpired:
        timed_out = True
        stderr = "Execution timed out after 10 seconds."
        exit_code = -1
    except FileNotFoundError:
        stderr = "Docker is not installed or not running."
        exit_code = -2
    except Exception as exc:
        stderr = str(exc)
        exit_code = -1
    finally:
        elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
        try:
            os.unlink(tmp_path)
        except Exception:
            pass

    return {
        "stdout": stdout,
        "stderr": stderr,
        "execution_time_ms": elapsed_ms,
        "timed_out": timed_out,
        "exit_code": exit_code,
    }


# ═══════════════════════════════════════════════════════════════════
# 3. evaluate_code
# ═══════════════════════════════════════════════════════════════════

def evaluate_code(code: str, language: str, session_id: str) -> dict:
    """
    Full code evaluation pipeline: static analysis → sandbox execution.

    Workflow:
        1. Run static analysis.
        2. If any HIGH-severity issue is found, reject immediately.
        3. Otherwise execute in sandbox and return combined result.

    Args:
        code:       Source code submitted by the candidate.
        language:   Programming language string.
        session_id: Used for sandbox temp-file naming.

    Returns:
        {
            "passed":             bool,
            "stdout":             str,
            "stderr":             str,
            "execution_time_ms":  float,
            "static_issues":      list[dict],
            "timed_out":          bool,
            "reason":             str   (only present on failure)
        }
    """
    static_issues = run_static_analysis(code, language)

    # Block on any HIGH-severity security violation
    critical = [i for i in static_issues if i["severity"].upper() == "HIGH"]
    if critical:
        return {
            "passed": False,
            "reason": "Security violation detected",
            "static_issues": static_issues,
            "stdout": "",
            "stderr": "",
            "execution_time_ms": 0.0,
            "timed_out": False,
        }

    # Execute in sandbox
    sandbox_result = execute_in_sandbox(code, language, session_id)

    passed = (
        sandbox_result["exit_code"] == 0
        and not sandbox_result["timed_out"]
    )

    return {
        "passed": passed,
        "stdout": sandbox_result["stdout"],
        "stderr": sandbox_result["stderr"],
        "execution_time_ms": sandbox_result["execution_time_ms"],
        "static_issues": static_issues,
        "timed_out": sandbox_result["timed_out"],
    }
