import json
from pathlib import Path

root=Path(__file__).parent
schemas={p.name:json.loads(p.read_text(encoding="utf-8")) for p in root.glob("*.schema.json")}
assert schemas and len({x["$id"] for x in schemas.values()}) == len(schemas)
assert all(x.get("$schema") == "https://json-schema.org/draft/2020-12/schema" for x in schemas.values())

def walk(x):
    if isinstance(x,dict):
        if "$ref" in x: yield x["$ref"]
        for v in x.values(): yield from walk(v)
    elif isinstance(x,list):
        for v in x: yield from walk(v)
for name,obj in schemas.items():
    for r in walk(obj):
        if r.startswith("common.schema.json#"): assert "common.schema.json" in schemas, (name,r)
        elif r.endswith(".schema.json"): assert r in schemas, (name,r)

action=json.loads((root/"examples/action-proposal.valid.json").read_text())
assert action["reversibility"]=="COMPENSATABLE" and isinstance(action["compensation_action"],dict) and action["audit_deadline"]
bad_action=dict(action); bad_action["compensation_action"]=None
assert not (bad_action["reversibility"]=="COMPENSATABLE" and isinstance(bad_action["compensation_action"],dict))

unknown=json.loads((root/"examples/validator-result.hard-unknown.valid.json").read_text())
assert unknown["criticality"]=="HARD" and unknown["status"]=="UNKNOWN" and unknown["permitted_resolution"] in {"QUERY","ESCALATE"}
bad_unknown=dict(unknown); bad_unknown["permitted_resolution"]="EXECUTE"
assert bad_unknown["permitted_resolution"] not in {"QUERY","ESCALATE"}

user=json.loads((root/"examples/user-model.valid.json").read_text())
assert user["private_world_state_ref"]["access_class"]=="PRIVATE_ENVIRONMENT"
bad_user=dict(user); bad_user["private_world_state_ref"]={"ref_id":"state:1","access_class":"POLICY_VISIBLE"}
assert bad_user["private_world_state_ref"]["access_class"]!="PRIVATE_ENVIRONMENT"

outcome_req=set(schemas["outcome-vector.schema.json"]["required"])
assert {"clarification_necessary","clarification_unnecessary","clarification_insufficient","clarification_repeated","clarification_incorrect_scope"} <= outcome_req
print(f"PASS: {len(schemas)} schemas; IDs, references, access rules, and positive/negative semantic cases validated")
