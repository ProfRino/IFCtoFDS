"""Read-only application probes for review reanalysis. Only writes evidence alongside this file."""
import sys, json, re, hashlib, os, subprocess, platform
from pathlib import Path
ROOT = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).resolve().parents[4]
sys.path.insert(0,str(ROOT))
from ifc_to_fds.fire.scenario_emitter import emit_fire_scenario, EVSelection
from ifc_to_fds.domain.mapping import MappingPlan, MappingDecision, MappingStrategy
from ifc_to_fds.domain.bim.bounding_box import BoundingBox
from ifc_to_fds.domain.mep.hvac import EndpointSpec
from ifc_to_fds.validation.effective import check_opening_grid_alignment
from ifc_to_fds.validation.parser import parse_fds
OUT = Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else Path(__file__).parent / "rerun"
OUT.mkdir(exist_ok=True)
ev = EVSelection(preset_id="auto-nmc", position=(5,5,0.75), pack_kwh=40, peak_hrr_mw=7)
bundle = emit_fire_scenario(MappingPlan(), "a"*64, [ev])
report = {"python": sys.version, "platform": platform.platform(), "date":"2026-11-04", "probes":{}}
pr=report["probes"]
pr["energy_and_hf"]={"emitted":True,"comments":[s for s in bundle.fds_fragment.splitlines() if "Energy balance" in s or "HF=" in s or "HYDROGEN" in s],
 "bundle_fields":list(type(bundle).model_fields),
 "hf_references":[s for s in bundle.fds_fragment.splitlines() if "HF" in s or "FLUORIDE" in s]}
pr["opening_grid"]=[{"xb":xb,"result":check_opening_grid_alignment(xb,0.2)} for xb in [
[0,.9,0,.3,0,2.1],[0,1.2,0,.2,0,2.1],[0,1.8,0,.25,0,2.1],[0,1.5,0,.35,0,1.2],[0,.15,0,.15,0,.15]]]
dangling=emit_fire_scenario(MappingPlan(),"a"*64,[ev],opening_states={"missing":{"state":"OPEN","event_time_s":1}})
pr["missing_opening"]={"emitted":True,"lines":dangling.fds_fragment.split("! --- Opening & Boundary Controls ---")[1]}
source="&TIME T_END=1.8E3 /"
match=re.search(r"&TIME\s+[^/]*?T_END\s*=\s*([\d.]+)",source)
rewritten=re.sub(r"(&TIME\s+[^/]*?T_END\s*=\s*)[\d.]+",r"\g<1>"+f"{1936.2:.1f}",source)
pr["time_exponent"]={"input":source,"read_value":float(match.group(1)),"rewritten":rewritten}
try:
 EndpointSpec(kind="VENT",vent_xb=(0,1,0,1,0,1))
 pr["nonplanar_vent"]="ACCEPTED"
except ValueError as e:
 pr["nonplanar_vent"]={"blocked_at_schema":True,"error":str(e)}
decision=MappingDecision(entity_key="DOOR",strategy=MappingStrategy.OBST,simulation_role="DOOR",fds_representation="OBST",representation_bounds=BoundingBox(xmin=.4,xmax=.6,ymin=.2,ymax=.8,zmin=.2,zmax=.8))
solver=ROOT/".deps/fds-6.11.1/firemodels/FDS6/bin/fds_openmp.exe"
pr["door_solver"]={}
for variant in ["OPEN","CLOSED","OPEN_WITH_XYZ","CLOSED_WITH_XYZ"]:
 state=variant.split("_WITH")[0]
 b=emit_fire_scenario(MappingPlan(decisions=[decision]),"a"*64,[ev],opening_states={"DOOR":{"state":state,"event_time_s":1}})
 control=b.fds_fragment.split("! --- Opening & Boundary Controls ---")[1]
 if variant.endswith("WITH_XYZ"):
  control=control.replace("QUANTITY='TIME'", "XYZ=0.1,0.1,0.1, QUANTITY='TIME'")
 text="&HEAD CHID='door_"+state.lower()+"' /\n&MESH IJK=10,10,10, XB=0,1,0,1,0,1 /\n&TIME T_END=2.0 /\n&DUMP DT_DEVC=0.1, DT_CTRL=0.1 /\n"+control+"\n&TAIL /\n"
 d=OUT/variant.lower(); d.mkdir(exist_ok=True)
 (d/"input.fds").write_bytes(text.encode())
 info={"emitted_control":control,"input_sha256":hashlib.sha256(text.encode()).hexdigest()}
 if solver.is_file():
  env=dict(os.environ);env["OMP_NUM_THREADS"]="1";env["PATH"]=str(solver.parent/"mpi")+os.pathsep+env.get("PATH","")
  p=subprocess.run([str(solver),"input.fds"],cwd=d,env=env,capture_output=True,timeout=45,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
  (d/"stdout.log").write_bytes(p.stdout);(d/"stderr.log").write_bytes(p.stderr)
  info.update(exit_code=p.returncode,solver_sha256=hashlib.sha256(solver.read_bytes()).hexdigest())
  log=(p.stdout+p.stderr).decode(errors="replace")
  info["solver_errors"]=[s.strip() for s in log.splitlines() if "ERROR" in s]
  info["completed"]="STOP: FDS completed successfully" in log
  info["variant"]=variant
  for f in d.glob("*.csv"):
   if "ctrl" in f.name:
    info[f.name]=f.read_text()
  smv=next(d.glob("*.smv"),None)
  if smv:
   ls=smv.read_text().splitlines()
   info["obstruction_events"]=[ls[i:i+3] for i,l in enumerate(ls) if any(t in l for t in ("SHOW_OBST","HIDE_OBST"))]
 else: info["status"]="NOT_RUN"
 pr["door_solver"][variant]=info
report["source_sha256"]={str(p.relative_to(ROOT)).replace("\\","/"):hashlib.sha256(p.read_bytes()).hexdigest() for p in [
 ROOT/"ifc_to_fds/fire/scenario_emitter.py", ROOT/"ifc_to_fds/validation/effective.py", ROOT/"ifc_to_fds/adapters/jobs/runner.py",
 ROOT/"ifc_to_fds/validation/runner.py",ROOT/"ifc_to_fds/validation/engine.py",ROOT/"docs/audit/Review-Toan-Dien-IFCtoFDS-.docx"]}
(OUT/"probes.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps(report,ensure_ascii=False,indent=2))

