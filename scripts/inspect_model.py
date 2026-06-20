"""Introspect the OmniParser Replicate model: version id + input/output schema.
Free — only fetches model metadata, runs no prediction.
"""

from __future__ import annotations

import json

from dotenv import load_dotenv

load_dotenv()

import replicate  # noqa: E402

m = replicate.models.get("microsoft/omniparser-v2")
print("model:", f"{m.owner}/{m.name}")
v = getattr(m, "latest_version", None)
print("latest_version id:", getattr(v, "id", None))

schema = getattr(v, "openapi_schema", None) if v else None
if schema:
    comps = schema.get("components", {}).get("schemas", {})
    inp = comps.get("Input", {}).get("properties", {})
    print("\nINPUT properties:")
    for name, spec in inp.items():
        print(f"  {name}: {spec.get('type', spec.get('allOf', '?'))} default={spec.get('default')}")
    print("\nOUTPUT schema:")
    print(json.dumps(comps.get("Output", {}), indent=2)[:1800])
else:
    print("no openapi schema available")
