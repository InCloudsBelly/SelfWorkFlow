import json
from pathlib import Path
import sys
import time


arguments = sys.argv[1:]
output = Path(arguments[arguments.index("--output-last-message") + 1])
model = arguments[arguments.index("--model") + 1]
effort = arguments[arguments.index("-c") + 1].split("=", 1)[1]
prompt = arguments[-1]
if "fixtureMode: timeout" in prompt:
    time.sleep(5)
if "fixtureMode: nonzero" in prompt:
    raise SystemExit(7)
if "fixtureMode: drift" in prompt:
    Path("drift.txt").write_text("drift", encoding="utf-8")
if "fixtureMode: invalid" in prompt:
    output.write_text("not-json", encoding="utf-8")
else:
    result = {
        "schemaVersion": 1,
        "scenarioId": "fixture",
        "summary": "fixture result",
        "criticalPassed": [],
        "bonusPassed": [],
        "prohibitedHits": [],
        "model": model,
        "reasoningEffort": effort,
    }
    output.write_text(json.dumps(result), encoding="utf-8")
print(json.dumps({"type": "completed"}))
