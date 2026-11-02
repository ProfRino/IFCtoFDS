# MEP Duct & HVAC Network Handling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve MEP duct/pipe conversion defects: fix Web/JS parser dropping fittings, prevent generic MEP elements from becoming solid obstacles, support FDS `&HVAC` namelist in syntax parser and serializer, and provide explicit HVAC network emission for ventilation ducts.

**Architecture:** 
1. Harmonize frontend `PRODUCT_TYPES` with `REVIEW_TYPES` in `js/ifc/ifc-adapter.js` and `js/workers/ifc-parse-shard-worker-inline.js`.
2. Extract MEP prefix constant and inspect both `ifc_type` and `type_class` across mapping policy functions in `ifc_to_fds/mapping/policy.py`.
3. Add `&HVAC` namelist definitions to FDS grammar in `ifc_to_fds/validation/parser.py`.
4. Add HVAC namelist rendering (`&HVAC TYPE_ID='DUCT'/'NODE'`) in `ifc_to_fds/mapping/exporter.py` when elements have `simulation_role == "HVAC"` or explicit duct parameters.

**Tech Stack:** Python 3.12, IfcOpenShell, Pytest, JavaScript (ES5/web-ifc adapter).

**Spec:** `docs/agent-context/docs/context/10_MEP_HVAC_PCCC.md` and Comprehensive Audit Review Findings.

## Global Constraints
- Do not create phantom smoke barriers in FDS (no solid `&OBST` for air conduits).
- Preserve 100% of MEP entities in inventory and review layers.
- Maintain FDS syntax validity and strict schema compliance.
- Keep all existing 448 unit/integration tests passing.

## Review Focus
1. `IfcDuctFitting`, `IfcPipeFitting`, `IfcDamper`, `IfcFan` omitted in browser worker: must be parsed into review objects.
2. `IfcBuildingElementProxy` with `type_class="IfcDuctSegment"`: must be classified as MEP, not converted to `PASSIVE_OBSTACLE`.
3. Generic `IfcDistributionElement`: must be detected as MEP candidate.
4. FDS file with `&HVAC TYPE_ID='DUCT'`: parser must recognize without syntax error.
5. Exporting duct under HVAC policy: must emit `&HVAC` or reference geometry, never solid concrete `&OBST`.

---

### Task 1: Fix JS IFC Adapter PRODUCT_TYPES & Worker Sync

**Files:**
- Modify: `js/ifc/ifc-adapter.js:20-40`
- Modify: `js/workers/ifc-parse-shard-worker-inline.js:20-40`
- Test: `scripts/test-workbench-feature4.js` (or node check)

**Interfaces:**
- Consumes: Raw STEP IFC text
- Produces: `ifcScene.elements` with all MEP types included

- [ ] **Step 1: Write test or check script verifying PRODUCT_TYPES has all REVIEW_TYPES**
- [ ] **Step 2: Add missing 8 MEP types to PRODUCT_TYPES in `js/ifc/ifc-adapter.js`**
  (`IFCDUCTFITTING`, `IFCAIRTERMINALBOX`, `IFCDUCTSILENCER`, `IFCFAN`, `IFCDAMPER`, `IFCPIPEFITTING`, `IFCVALVE`, `IFCPUMP`, `IFCDISTRIBUTIONELEMENT`)
- [ ] **Step 3: Synchronize `js/workers/ifc-parse-shard-worker-inline.js` with the updated list**
- [ ] **Step 4: Verify web parsing tests pass**
- [ ] **Step 5: Commit**
  `git commit -am "fix(js): add missing MEP types to PRODUCT_TYPES and worker"`

---

### Task 2: Standardize Mapping Policy and Generic MEP Classification

**Files:**
- Modify: `ifc_to_fds/mapping/policy.py:20-120, 160-220`
- Test: `tests/test_audit_remediation.py`

**Interfaces:**
- Consumes: `CanonicalElement`
- Produces: `MappingStrategy`, `simulation_role`

- [ ] **Step 1: Write failing test for `IfcBuildingElementProxy` with `type_class="IfcDuctSegment"` in `tests/test_audit_remediation.py`**
- [ ] **Step 2: Define `MEP_PREFIXES` module-level constant in `policy.py`**
- [ ] **Step 3: Update `determine_element_strategy` to check both `ifc_type` and `type_class` using `MEP_PREFIXES`**
- [ ] **Step 4: Add `IFCDISTRIBUTIONELEMENT` and `IFCDISTRIBUTIONFLOWELEMENT` to MEP handling**
- [ ] **Step 5: Support `"HVAC"` as valid decision action in `validate_decisions`**
- [ ] **Step 6: Run pytest to verify passes**
- [ ] **Step 7: Commit**
  `git commit -am "fix(mapping): unify MEP prefixes and type_class evaluation in policy"`

---

### Task 3: Support `&HVAC` Namelist in FDS Syntax Parser

**Files:**
- Modify: `ifc_to_fds/validation/parser.py:80-140`
- Test: `tests/test_validation_engine.py`

**Interfaces:**
- Consumes: FDS file text with `&HVAC`
- Produces: `ParsedFds` without flagging `HVAC` as unsupported namelist

- [ ] **Step 1: Write failing test in `tests/test_validation_engine.py` parsing `&HVAC TYPE_ID='DUCT', ID='D1', NODE_ID='N1','N2' /`**
- [ ] **Step 2: Add `"HVAC"` definition and allowed parameters to `allowed` dict in `ifc_to_fds/validation/parser.py`**
- [ ] **Step 3: Run pytest to verify test passes**
- [ ] **Step 4: Commit**
  `git commit -am "feat(parser): add &HVAC namelist grammar support to FDS parser"`

---

### Task 4: HVAC Namelist Serialization Support in FDS Serializer

**Files:**
- Modify: `ifc_to_fds/mapping/exporter.py:280-340`
- Test: `tests/test_audit_remediation.py`

**Interfaces:**
- Consumes: `CanonicalModel` with duct elements
- Produces: Serialized FDS string containing `&HVAC` records when appropriate

- [ ] **Step 1: Write failing test for serializing element with `simulation_role == "HVAC"` or duct geometry**
- [ ] **Step 2: Implement HVAC serialization helper in `exporter.py`**
- [ ] **Step 3: Ensure metal material `SURF_ID='STEEL'` is used for MEP elements instead of hardcoded `'CONCRETE'` when emitted**
- [ ] **Step 4: Run pytest to verify test passes**
- [ ] **Step 5: Commit**
  `git commit -am "feat(exporter): support HVAC duct serialization and appropriate material surfaces"`

---

### Task 5: End-to-End Verification & Documentation Update

**Files:**
- Modify: `README.md`
- Test: Full test suite (`pytest tests/`)

- [ ] **Step 1: Run complete test suite `pytest tests/`**
- [ ] **Step 2: Update documentation in README.md regarding MEP duct handling and HVAC support**
- [ ] **Step 3: Final review and report to user**
