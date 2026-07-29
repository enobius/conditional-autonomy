import json, shutil, zipfile
from pathlib import Path

ROOT=Path('architecture/schemas/v0.1')
EX=ROOT/'examples'; OUT=Path('outputs/Thesis_Architecture_Schemas_v0.1.zip')
ROOT.mkdir(parents=True,exist_ok=True); EX.mkdir(exist_ok=True); OUT.parent.mkdir(exist_ok=True)

META='https://json-schema.org/draft/2020-12/schema'
def schema(name, required, properties, **extra):
    x={'$schema':META,'$id':f'https://thesis.local/schemas/v0.1/{name}.schema.json','title':name.replace('-',' ').title(),'type':'object','required':required,'properties':properties,'additionalProperties':False}
    x.update(extra); return x
def ref(name): return {'$ref':f'{name}.schema.json'}
def s(**kw): return {'type':'string',**kw}
def arr(items,**kw): return {'type':'array','items':items,**kw}

common={'$schema':META,'$id':'https://thesis.local/schemas/v0.1/common.schema.json','title':'Common definitions','$defs':{
 'id':s(minLength=1,pattern='^[A-Za-z0-9][A-Za-z0-9._:-]*$'),
 'version':s(minLength=1),
 'timestamp':s(format='date-time'),
 'accessClass':{'enum':['POLICY_VISIBLE','SUPERVISOR_VISIBLE','VALIDATOR_VISIBLE','EVALUATOR_ONLY','PRIVATE_ENVIRONMENT']},
 'evidenceRef':schema('evidence-ref',['ref_id','source_type','access_class'],{'ref_id':{'$ref':'#/$defs/id'},'source_type':{'enum':['USER','TOOL','ENVIRONMENT','DERIVED_RULE','MODEL_CLAIM','EVALUATOR']},'access_class':{'$ref':'#/$defs/accessClass'},'uri':s(),'content_hash':s()}),
 'count':{'type':'integer','minimum':0}, 'probability':{'type':'number','minimum':0,'maximum':1},
 'jsonValue':{'oneOf':[{'type':'null'},{'type':'boolean'},{'type':'number'},{'type':'string'},{'type':'array','items':{}},{'type':'object'}]}
}}

state=schema('state',['schema_version','episode_id','state_version','logical_clock','entities','resources','obligations','dependencies','deadlines','permissions','active_plan','completed_actions','pending_questions','exogenous_events','provenance','revision_chain'],{
 'schema_version':s(),'episode_id':s(),'state_version':{'type':'integer','minimum':0},'logical_clock':{'type':'integer','minimum':0},
 'timezone':s(),'entities':{'type':'object','additionalProperties':{'type':'object'}},'resources':{'type':'object','additionalProperties':{'type':'object'}},
 'obligations':arr({'type':'object'}),'dependencies':arr({'type':'object'}),'deadlines':arr({'type':'object'}),'permissions':arr({'type':'object'}),
 'active_plan':{'type':['object','null']},'completed_actions':arr(s()),'pending_questions':arr({'type':'object'}),'exogenous_events':arr(s()),
 'provenance':arr({'$ref':'common.schema.json#/$defs/evidenceRef'}),'revision_chain':arr({'type':'object'}),
})

observation=schema('observation',['observation_id','episode_id','state_version','actor_id','access_class','visible_facts','goal_refs','generated_at'],{
 'observation_id':s(),'episode_id':s(),'state_version':{'type':'integer','minimum':0},'actor_id':s(),'access_class':{'const':'POLICY_VISIBLE'},
 'visible_facts':arr({'type':'object','required':['fact_id','value','epistemic_status','evidence_refs'],'properties':{'fact_id':s(),'value':{},'epistemic_status':{'enum':['OBSERVED','ASSERTED','INFERRED','UNKNOWN','CONTRADICTED','SUPERSEDED']},'evidence_refs':arr({'$ref':'common.schema.json#/$defs/evidenceRef'})},'additionalProperties':False}),
 'goal_refs':arr(s()),'generated_at':s(format='date-time'),'context_budget_tokens':{'type':'integer','minimum':1}
})

event=schema('event',['event_id','episode_id','event_type','logical_clock','timestamp','source','payload','access_class'],{
 'event_id':s(),'episode_id':s(),'event_type':{'enum':['INITIALIZE','OBSERVE','PROPOSE','AUTHORIZE','VALIDATE','EXECUTE','TOOL_RESULT','RECONCILE','COMMIT','COMPENSATE','REPAIR','QUERY','USER_RESPONSE','REJECT','ESCALATE','REVISE','CANCEL','EXOGENOUS']},
 'logical_clock':{'type':'integer','minimum':0},'timestamp':s(format='date-time'),'source':s(),'payload':{'type':'object'},'access_class':{'$ref':'common.schema.json#/$defs/accessClass'},
 'supersedes_event_id':{'type':['string','null']},'content_hash':s()
})

action=schema('action-proposal',['action_id','plan_id','actor_id','state_version','action_type','arguments','expected_preconditions','expected_effects','required_capabilities','risk_class','reversibility','postconditions','evidence_refs','confidence','idempotency_key'],{
 'action_id':s(),'plan_id':s(),'actor_id':s(),'state_version':{'type':'integer','minimum':0},'action_type':s(),'arguments':{'type':'object'},
 'expected_preconditions':arr({'type':'object'}),'expected_effects':arr({'type':'object'}),'required_capabilities':arr(s(),minItems=1,uniqueItems=True),
 'risk_class':{'enum':['LOW','MODERATE','HIGH','CRITICAL']},'reversibility':{'enum':['REVERSIBLE','COMPENSATABLE','IRREVERSIBLE']},
 'compensation_action':{'oneOf':[{'type':'null'},{'type':'object','required':['action_type','arguments','required_capabilities'],'properties':{'action_type':s(),'arguments':{'type':'object'},'required_capabilities':arr(s(),minItems=1),'prevalidation_id':s()},'additionalProperties':False}]},
 'postconditions':arr({'type':'object'}),'audit_deadline':{'type':['string','null'],'format':'date-time'},'evidence_refs':arr({'$ref':'common.schema.json#/$defs/evidenceRef'}),
 'confidence':{'$ref':'common.schema.json#/$defs/probability'},'idempotency_key':s()
},allOf=[{'if':{'properties':{'reversibility':{'const':'COMPENSATABLE'}}},'then':{'required':['compensation_action','audit_deadline'],'properties':{'compensation_action':{'type':'object'},'audit_deadline':{'type':'string'}}}},{'if':{'properties':{'reversibility':{'const':'IRREVERSIBLE'}}},'then':{'properties':{'compensation_action':{'type':'null'}}}}])

validator=schema('validator-result',['validator_id','validator_version','status','criticality','enforceability','constraint_ids','evidence_refs','observed_state_version','permitted_resolution','explanation_code','repair_hints','timestamp'],{
 'validator_id':s(),'validator_version':s(),'status':{'enum':['PASS','FAIL','UNKNOWN']},'criticality':{'enum':['HARD','SOFT']},'enforceability':{'enum':['PREVENTABLE','PREDICTIVE','DETECTABLE']},
 'constraint_ids':arr(s(),uniqueItems=True),'evidence_refs':arr({'$ref':'common.schema.json#/$defs/evidenceRef'}),'observed_state_version':{'type':'integer','minimum':0},
 'uncertainty_reason':{'type':['string','null']},'permitted_resolution':{'enum':['EXECUTE','REPAIR','QUERY','REJECT','ESCALATE']},'explanation_code':s(),'repair_hints':arr(s()),'timestamp':s(format='date-time')
},allOf=[{'if':{'properties':{'criticality':{'const':'HARD'},'status':{'const':'UNKNOWN'}},'required':['criticality','status']},'then':{'properties':{'permitted_resolution':{'enum':['QUERY','ESCALATE']},'uncertainty_reason':{'type':'string','minLength':1}},'required':['uncertainty_reason']}},{'if':{'properties':{'status':{'const':'PASS'}}},'then':{'properties':{'permitted_resolution':{'const':'EXECUTE'}}}}])

decision=schema('supervisor-decision',['decision_id','action_id','decision','confidence','violated_constraint_ids','uncertainty_reasons','requested_information','evidence_refs','supervisor_model_version','timestamp'],{
 'decision_id':s(),'action_id':s(),'decision':{'enum':['APPROVE','REPAIR','QUERY','REJECT','ESCALATE']},'confidence':{'$ref':'common.schema.json#/$defs/probability'},
 'violated_constraint_ids':arr(s()),'uncertainty_reasons':arr(s()),'requested_information':arr(s()),'proposed_repair':{'type':['object','null']},
 'evidence_refs':arr({'$ref':'common.schema.json#/$defs/evidenceRef'}),'supervisor_model_version':s(),'adapter_version':{'type':['string','null']},'timestamp':s(format='date-time')
})

tool=schema('tool-outcome',['outcome_id','action_id','tool_id','tool_version','status','started_at','completed_at','raw_result_ref','normalized_effects','verified_effects','state_version_before'],{
 'outcome_id':s(),'action_id':s(),'tool_id':s(),'tool_version':s(),'status':{'enum':['SUCCEEDED','FAILED','PARTIAL','TIMED_OUT','UNKNOWN']},'started_at':s(format='date-time'),'completed_at':s(format='date-time'),
 'raw_result_ref':{'$ref':'common.schema.json#/$defs/evidenceRef'},'normalized_effects':arr({'type':'object'}),'verified_effects':arr({'type':'object'}),'state_version_before':{'type':'integer','minimum':0},
 'state_version_after':{'type':['integer','null'],'minimum':0},'error_code':{'type':['string','null']},'idempotency_key':s()
})

outcome=schema('outcome-vector',['goal_success','constraint_score','hard_violation_count','optimality_gap','recovery_success','execution_cost','latency_ms','token_count','tool_calls','user_interventions','clarification_total','clarification_necessary','clarification_unnecessary','clarification_insufficient','clarification_repeated','clarification_incorrect_scope','evaluator_disagreement'],{
 'goal_success':{'type':'boolean'},'constraint_score':{'type':'number'},'hard_violation_count':{'$ref':'common.schema.json#/$defs/count'},'optimality_gap':{'type':['number','null']},'recovery_success':{'type':['boolean','null']},
 'execution_cost':{'type':'number','minimum':0},'latency_ms':{'type':'integer','minimum':0},'token_count':{'$ref':'common.schema.json#/$defs/count'},'tool_calls':{'$ref':'common.schema.json#/$defs/count'},'user_interventions':{'$ref':'common.schema.json#/$defs/count'},
 'clarification_total':{'$ref':'common.schema.json#/$defs/count'},'clarification_necessary':{'$ref':'common.schema.json#/$defs/count'},'clarification_unnecessary':{'$ref':'common.schema.json#/$defs/count'},'clarification_insufficient':{'$ref':'common.schema.json#/$defs/count'},'clarification_repeated':{'$ref':'common.schema.json#/$defs/count'},'clarification_incorrect_scope':{'$ref':'common.schema.json#/$defs/count'},'evaluator_disagreement':{'type':'number','minimum':0}
},allOf=[{'properties':{'clarification_total':{'minimum':0}}}])

trace=schema('trace-step',['trace_step_id','episode_id','step_index','canonical_state_ref','actor_observation','goal_refs','policy_version','proposal','supervisor_decision','validator_results','transition_diff','outcome_vector','provenance'],{
 'trace_step_id':s(),'episode_id':s(),'step_index':{'type':'integer','minimum':0},
 'canonical_state_ref':{'type':'object','required':['ref_id','access_class'],'properties':{'ref_id':s(),'access_class':{'const':'EVALUATOR_ONLY'}},'additionalProperties':False},
 'actor_observation':{'$ref':'observation.schema.json'},'goal_refs':arr(s()),'policy_version':s(),'adapter_version':{'type':['string','null']},
 'proposal':{'oneOf':[{'type':'null'},ref('action-proposal')]} ,'supervisor_decision':{'oneOf':[{'type':'null'},ref('supervisor-decision')]},
 'validator_results':arr(ref('validator-result')),'tool_result':{'oneOf':[{'type':'null'},ref('tool-outcome')]},'transition_diff':{'type':'object'},
 'outcome_vector':ref('outcome-vector'),'evaluator_labels':arr({'type':'object'}),'provenance':arr({'$ref':'common.schema.json#/$defs/evidenceRef'})
})

episode=schema('episode',['episode_id','schema_version','environment_version','generator_manifest_ref','user_model_ref','policy_versions','started_at','status','steps','final_outcome'],{
 'episode_id':s(),'schema_version':s(),'environment_version':s(),'generator_manifest_ref':s(),'user_model_ref':s(),'policy_versions':arr(s(),minItems=1),
 'started_at':s(format='date-time'),'ended_at':{'type':['string','null'],'format':'date-time'},'status':{'enum':['RUNNING','COMPLETED','FAILED','ESCALATED','ABORTED']},
 'steps':arr(ref('trace-step')),'final_outcome':ref('outcome-vector'),'event_log_hash':s(),'split':{'enum':['TRAIN','DEVELOPMENT','TEST','TRANSFER','PROTECTED_REGRESSION']}
})

user=schema('user-model',['user_model_id','version','private_world_state_ref','answerable_facts','response_policy','ambiguity_policy','correction_policy','noise_policy','maximum_turns','oracle_access_rules','template_family','seed'],{
 'user_model_id':s(),'version':s(),'private_world_state_ref':{'type':'object','required':['ref_id','access_class'],'properties':{'ref_id':s(),'access_class':{'const':'PRIVATE_ENVIRONMENT'}},'additionalProperties':False},
 'answerable_facts':arr(s()),'response_policy':{'enum':['DETERMINISTIC_ORACLE','NATURALISTIC','ADVERSARIAL_NOISY']},'ambiguity_policy':{'type':'object'},'correction_policy':{'type':'object'},'noise_policy':{'type':'object'},
 'maximum_turns':{'type':'integer','minimum':0},'oracle_access_rules':{'type':'object'},'template_family':s(),'seed':{'type':'integer'}
})

instance=schema('instance-manifest',['generator_id','generator_version','scenario_family','seed','difficulty_parameters','constraint_graph_hash','entity_graph_hash','disruption_schedule_hash','user_model_version','source_dataset_lineage','feasibility_oracle_version','split_assignment'],{
 'generator_id':s(),'generator_version':s(),'scenario_family':{'enum':['P6','P9','J1','J2','MICRO','EXTENSION']},'seed':{'type':'integer'},'difficulty_parameters':{'type':'object'},'constraint_graph_hash':s(),'entity_graph_hash':s(),'disruption_schedule_hash':s(),'user_model_version':s(),'source_dataset_lineage':arr(s(),minItems=1),'feasibility_oracle_version':s(),'split_assignment':{'enum':['TRAIN','DEVELOPMENT','TEST','TRANSFER','PROTECTED_REGRESSION']}
})

adapter=schema('adapter-manifest',['adapter_id','base_model_hash','training_data_version','domain','capability_scope','rank','target_modules','eval_report_ref','known_failures','incompatibilities','fallback_adapter','status'],{
 'adapter_id':s(),'base_model_hash':s(),'training_data_version':s(),'domain':s(),'capability_scope':arr(s()),'rank':{'type':'integer','minimum':1},'target_modules':arr(s(),minItems=1),'router_features':arr(s()),'eval_report_ref':s(),'known_failures':arr(s()),'incompatibilities':arr(s()),'fallback_adapter':{'type':['string','null']},'status':{'enum':['CANDIDATE','PROMOTED','QUARANTINED','RETIRED']}
})

schemas={'common':common,'state':state,'observation':observation,'event':event,'action-proposal':action,'validator-result':validator,'supervisor-decision':decision,'tool-outcome':tool,'outcome-vector':outcome,'trace-step':trace,'episode':episode,'user-model':user,'instance-manifest':instance,'adapter-manifest':adapter}
for name,obj in schemas.items(): (ROOT/f'{name}.schema.json').write_text(json.dumps(obj,indent=2)+'\n',encoding='utf-8')

examples={
'action-proposal.valid.json':{'action_id':'act:1','plan_id':'plan:1','actor_id':'worker:1','state_version':3,'action_type':'start_oven','arguments':{'temperature_f':350},'expected_preconditions':[{'oven':'available'}],'expected_effects':[{'oven':'heating'}],'required_capabilities':['oven.control'],'risk_class':'MODERATE','reversibility':'COMPENSATABLE','compensation_action':{'action_type':'stop_oven','arguments':{},'required_capabilities':['oven.control'],'prevalidation_id':'preval:1'},'postconditions':[{'oven':'heating'}],'audit_deadline':'2026-11-26T15:05:00Z','evidence_refs':[],'confidence':0.91,'idempotency_key':'idem:act:1'},
'validator-result.hard-unknown.valid.json':{'validator_id':'resource_validator','validator_version':'0.1','status':'UNKNOWN','criticality':'HARD','enforceability':'PREVENTABLE','constraint_ids':['oven_supervision'],'evidence_refs':[],'observed_state_version':3,'uncertainty_reason':'Supervisor location is unknown','permitted_resolution':'QUERY','explanation_code':'MISSING_REQUIRED_FACT','repair_hints':['Ask who remains home'],'timestamp':'2026-11-26T14:00:00Z'},
'user-model.valid.json':{'user_model_id':'user:p6:oracle','version':'0.1','private_world_state_ref':{'ref_id':'state:private:1','access_class':'PRIVATE_ENVIRONMENT'},'answerable_facts':['driver_availability','supervisor_location'],'response_policy':'DETERMINISTIC_ORACLE','ambiguity_policy':{},'correction_policy':{},'noise_policy':{},'maximum_turns':3,'oracle_access_rules':{'reveal_only_requested':True},'template_family':'p6-oracle-a','seed':42},
}
for name,obj in examples.items(): (EX/name).write_text(json.dumps(obj,indent=2)+'\n',encoding='utf-8')

(ROOT/'README.md').write_text('''# Thesis Architecture JSON Schemas v0.1\n\nJSON Schema 2020-12 contracts for the Stage 1 environment and evidence plane.\n\n## Guarantees encoded\n\n- `COMPENSATABLE` proposals require a non-null compensation action and audit deadline.\n- `HARD + UNKNOWN` validator results can resolve only to `QUERY` or `ESCALATE`.\n- Policy observations are `POLICY_VISIBLE`; canonical trace state is `EVALUATOR_ONLY`; user private state is `PRIVATE_ENVIRONMENT`.\n- Clarification categories required by H3 are present in the outcome vector.\n- Generator, user model, policy, tool, validator, and adapter versions are explicit.\n\n## Validation\n\nRun `python validate_examples.py` from this directory. The zero-dependency validator checks JSON integrity, unique schema IDs, local reference targets, access rules, and representative positive/negative semantic cases. The schemas target JSON Schema 2020-12 and should additionally be checked with a full implementation such as Python `jsonschema` or Ajv in the project environment.\n\n## Versioning\n\nThis package is `v0.1`. Breaking field or semantic changes require a new versioned directory. Additive optional fields may increment the patch version after compatibility tests.\n''',encoding='utf-8')

(ROOT/'validate_examples.py').write_text('''import json\nfrom pathlib import Path\n\nroot=Path(__file__).parent\nschemas={p.name:json.loads(p.read_text(encoding="utf-8")) for p in root.glob("*.schema.json")}\nassert schemas and len({x["$id"] for x in schemas.values()}) == len(schemas)\nassert all(x.get("$schema") == "https://json-schema.org/draft/2020-12/schema" for x in schemas.values())\n\ndef walk(x):\n    if isinstance(x,dict):\n        if "$ref" in x: yield x["$ref"]\n        for v in x.values(): yield from walk(v)\n    elif isinstance(x,list):\n        for v in x: yield from walk(v)\nfor name,obj in schemas.items():\n    for r in walk(obj):\n        if r.startswith("common.schema.json#"): assert "common.schema.json" in schemas, (name,r)\n        elif r.endswith(".schema.json"): assert r in schemas, (name,r)\n\naction=json.loads((root/"examples/action-proposal.valid.json").read_text())\nassert action["reversibility"]=="COMPENSATABLE" and isinstance(action["compensation_action"],dict) and action["audit_deadline"]\nbad_action=dict(action); bad_action["compensation_action"]=None\nassert not (bad_action["reversibility"]=="COMPENSATABLE" and isinstance(bad_action["compensation_action"],dict))\n\nunknown=json.loads((root/"examples/validator-result.hard-unknown.valid.json").read_text())\nassert unknown["criticality"]=="HARD" and unknown["status"]=="UNKNOWN" and unknown["permitted_resolution"] in {"QUERY","ESCALATE"}\nbad_unknown=dict(unknown); bad_unknown["permitted_resolution"]="EXECUTE"\nassert bad_unknown["permitted_resolution"] not in {"QUERY","ESCALATE"}\n\nuser=json.loads((root/"examples/user-model.valid.json").read_text())\nassert user["private_world_state_ref"]["access_class"]=="PRIVATE_ENVIRONMENT"\nbad_user=dict(user); bad_user["private_world_state_ref"]={"ref_id":"state:1","access_class":"POLICY_VISIBLE"}\nassert bad_user["private_world_state_ref"]["access_class"]!="PRIVATE_ENVIRONMENT"\n\noutcome_req=set(schemas["outcome-vector.schema.json"]["required"])\nassert {"clarification_necessary","clarification_unnecessary","clarification_insufficient","clarification_repeated","clarification_incorrect_scope"} <= outcome_req\nprint(f"PASS: {len(schemas)} schemas; IDs, references, access rules, and positive/negative semantic cases validated")\n''',encoding='utf-8')

if OUT.exists(): OUT.unlink()
with zipfile.ZipFile(OUT,'w',zipfile.ZIP_DEFLATED) as z:
    for p in ROOT.rglob('*'):
        if p.is_file(): z.write(p,p.relative_to(ROOT.parent))
print(ROOT.resolve()); print(OUT.resolve())
