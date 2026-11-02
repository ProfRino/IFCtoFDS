"""Strict parser for the emitted FDS subset, independent of the exporter."""

import json
import re
from dataclasses import dataclass, field
from typing import Any
import numpy as np
from ifc_to_fds.diagnostics import operation
from ifc_to_fds.core.canonical import BoundingBox, TriangleMesh
from ifc_to_fds.geometry.mesh import box_mesh


@dataclass
class FDSRecord:
    kind: str
    values: dict[str, list[Any]]
    source: dict = field(default_factory=dict)

    @property
    def id(self):
        return str(self.values.get("ID", [""])[0])

    def mesh(self):
        if self.kind in ("OBST", "HOLE"):
            xb = self.values.get("XB", [])
            if len(xb) != 6:
                raise ValueError("XB requires six coordinates")
            return box_mesh(
                BoundingBox(
                    **dict(zip(("xmin", "xmax", "ymin", "ymax", "zmin", "zmax"), xb))
                )
            )
        if self.kind == "GEOM":
            v, f = self.values.get("VERTS", []), self.values.get("FACES", [])
            if not v or len(v) % 3 or not f or len(f) % 4:
                raise ValueError("Invalid GEOM VERTS/FACES")
            if any(not float(x).is_integer() for x in f):
                raise ValueError("GEOM indices must be integers")
            faces = [[int(x) - 1 for x in f[i : i + 3]] for i in range(0, len(f), 4)]
            if any(x < 0 or x >= len(v) // 3 for face in faces for x in face):
                raise ValueError("GEOM vertex index out of range")
            return TriangleMesh(
                vertices=[v[i : i + 3] for i in range(0, len(v), 3)], faces=faces
            )
        raise ValueError("Not a solid record")


@dataclass
class ParsedFDS:
    records: list[FDSRecord] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    unsupported: list[str] = field(default_factory=list)

    @property
    def primitives(self):
        return [r for r in self.records if r.kind in ("OBST", "GEOM", "HOLE", "VENT")
                and not (r.kind == "VENT" and r.values.get("SURF_ID") == ["HVAC"])]

    @property
    def operational_records(self):
        return [r for r in self.records if r.kind == "HVAC"
                or (r.kind == "VENT" and r.values.get("SURF_ID") == ["HVAC"])]


def parse_value(token):
    token = token.strip()
    if token[:1] in ("'", '"') and token[-1:] == token[:1]:
        return token[1:-1].replace(token[0] * 2, token[0])
    if token.upper() in (".TRUE.", ".FALSE."):
        return token.upper() == ".TRUE."
    try:
        value = float(token.replace("D", "E").replace("d", "e"))
        if not np.isfinite(value):
            raise ValueError("Non-finite numeric value")
        return value
    except ValueError:
        raise ValueError(f"Unsupported or invalid value: {token[:80]}")


@operation("FDS_PARSE")
def parse_fds(text):
    parsed = ParsedFDS()
    source: dict[str, Any] = {}
    record = ""
    quote = None
    active = False
    i = 0
    seen = set()
    allowed = {
        "HEAD": {"CHID", "TITLE"},
        "TIME": {"T_END"},
        "MESH": {"ID", "IJK", "XB"},
        "SURF": {
            "ID",
            "COLOR",
            "RGB",
            "DEFAULT",
            "TRANSPARENCY",
            "HRRPUA",
            "RAMP_Q",
            "FUEL_ID",
            "MATL_ID",
            "BACKING",
            "THICKNESS",
        },
        "TAIL": set(),
        "OBST": {"ID", "XB", "SURF_ID", "CTRL_ID", "DEVC_ID"},
        "GEOM": {"ID", "VERTS", "FACES", "SURF_ID"},
        "HOLE": {"ID", "XB", "CTRL_ID", "DEVC_ID"},
        "VENT": {"ID", "XB", "SURF_ID", "CTRL_ID", "DEVC_ID"},
        "REAC": {
            "ID",
            "FUEL",
            "C",
            "H",
            "O",
            "N",
            "CO_YIELD",
            "SOOT_YIELD",
            "HEAT_OF_COMBUSTION",
            "FORMULA",
        },
        "RAMP": {"ID", "T", "F"},
        "DEVC": {
            "ID",
            "PROP_ID",
            "XYZ",
            "QUANTITY",
            "SETPOINT",
            "INITIAL_STATE",
            "CTRL_ID",
            "IOR",
        },
        "CTRL": {
            "ID",
            "FUNCTION_TYPE",
            "INPUT_ID",
            "LATCH",
            "DELAY",
            "CONSTANT",
        },
        "SPEC": {
            "ID",
            "FORMULA",
            "MASS_FRACTION_0",
            "LUMPED_COMPONENT_ONLY",
            "BACKGROUND",
            "SPEC_ID",
            "MW",
            "DENSITY",
        },
        "HVAC": {
            "ID",
            "AMBIENT",
            "GEOM",
            "TYPE_ID",
            "DUCT_ID",
            "NODE_ID",
            "VENT_ID",
            "AREA",
            "LENGTH",
            "LOSS",
            "ROUGHNESS",
            "FLOW",
            "VOLUME_FLOW",
            "MASS_FLOW",
            "XYZ",
            "DIAMETER",
            "PERIMETER",
            "FAN_ID",
            "DEVC_ID",
            "CTRL_ID",
            "DAMPER",
            "REVERSE",
            "CLEAN",
            "LOADING",
            "FILTER_ID",
            "AIRCOIL_ID",
        },
    }
    while i < len(text):
        c = text[i]
        if quote:
            record += c
            if c == quote:
                if i + 1 < len(text) and text[i + 1] == quote:
                    record += text[i + 1]
                    i += 1
                else:
                    quote = None
        elif c == "!":
            end = text.find("\n", i)
            if end == -1:
                end = len(text)
            comment = text[i + 1 : end].strip()
            if not active and re.match(r"IFC_SOURCE\b", comment):
                body = comment[len("IFC_SOURCE") :].strip().strip(",").strip()
                try:
                    if body.startswith("{"):
                        source = json.loads(body)
                        if not isinstance(source, dict):
                            raise ValueError("Expected source object")
                    else:
                        source = {"legacy": True}
                        for match in re.finditer(
                            r"(\w+)\s*=\s*('(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"|[^,()]+)",
                            body,
                        ):
                            source[match.group(1).lower()] = parse_value(match.group(2))
                        if "step_id" in source:
                            source["step_id"] = int(
                                str(source["step_id"]).lstrip("#").removesuffix(".0")
                            )
                except (ValueError, TypeError):
                    parsed.errors.append("Invalid IFC_SOURCE metadata")
            elif not active and re.search(r"IFC\s+entity\b", comment, re.IGNORECASE):
                step_m = re.search(r"entity\s+#?(\d+)", comment, re.IGNORECASE)
                guid_m = re.search(r"GUID\s*=\s*['\"]?([^;\s,'\"]+)['\"]?", comment, re.IGNORECASE)
                if step_m or guid_m:
                    source = {"legacy": True}
                    if step_m:
                        source["step_id"] = int(step_m.group(1))
                    if guid_m:
                        source["global_id"] = guid_m.group(1)
                else:
                    source = {}
            i = end - 1
        elif active and c in ("'", '"'):
            quote = c
            record += c
        elif c == "&":
            if active:
                parsed.errors.append("Unterminated namelist")
            active = True
            record = ""
        elif c == "/" and active:
            try:
                kind_match = re.match(r"\s*(\w+)", record)
                if not kind_match:
                    raise ValueError("Missing namelist name")
                kind = kind_match.group(1).upper()
                body = record[kind_match.end() :]
                # Split commas outside quoted strings, then collect key=value arrays.
                tokens = re.findall(
                    r"(?:'[^']*(?:''[^']*)*'|\"[^\"]*(?:\"\"[^\"]*)*\"|[^,])+", body
                )
                values = {}
                key = None
                for token in tokens:
                    token = token.strip()
                    if not token:
                        continue
                    match = re.match(
                        r"([A-Za-z_][\w]*(?:\([^)]*\))?)\s*=\s*([\s\S]*)", token
                    )
                    if match:
                        key = match.group(1).upper()
                        if key in values:
                            raise ValueError(f"Duplicate field {key}")
                        values[key] = []
                        token = match.group(2).strip()
                    if key is None:
                        raise ValueError("Value without field name")
                    if token:
                        values[key].append(parse_value(token))
                if kind not in allowed:
                    parsed.unsupported.append(f"Unsupported namelist {kind}")
                else:
                    parsed.unsupported.extend(
                        f"{kind}.{k}" for k in values if k not in allowed[kind]
                    )
                r = FDSRecord(kind, values, source)
                if r.id and kind != "RAMP":
                    identity = (
                        (kind, tuple(values.get("TYPE_ID", [])))
                        if kind == "HVAC" else kind
                        if kind not in ("OBST", "HOLE", "GEOM", "VENT")
                        else "PRIMITIVE",
                        r.id,
                    )
                    if identity in seen:
                        raise ValueError(f"Duplicate ID {r.id}")
                    seen.add(identity)
                if kind == "HEAD":
                    chid = values.get("CHID", [""])[0]
                    if not isinstance(chid, str) or not re.fullmatch(
                        r"[A-Za-z0-9][A-Za-z0-9_.-]{0,59}", chid
                    ):
                        raise ValueError("HEAD CHID must be a safe local basename")
                if kind == "MESH":
                    xb = values.get("XB", [])
                    ijk = values.get("IJK", [])
                    if (
                        len(xb) != 6
                        or len(ijk) != 3
                        or any(not float(x).is_integer() or x <= 0 for x in ijk)
                    ):
                        raise ValueError("Invalid MESH XB/IJK")
                    BoundingBox(
                        **dict(
                            zip(("xmin", "xmax", "ymin", "ymax", "zmin", "zmax"), xb)
                        )
                    )
                if kind in ("OBST", "GEOM", "HOLE"):
                    r.mesh()
                parsed.records.append(r)
            except (ValueError, TypeError, IndexError) as exc:
                parsed.errors.append(str(exc))
            active = False
            record = ""
            source = {}
        elif active:
            record += c
        elif not c.isspace():
            parsed.errors.append(
                f"Unexpected text outside namelist: {text[i : i + 30]}"
            )
            end = text.find("\n", i)
            i = len(text) if end == -1 else end - 1
        i += 1
    if active or quote:
        parsed.errors.append("Unterminated namelist or string")
    for kind in ("HEAD", "TIME", "MESH", "TAIL"):
        if not any(r.kind == kind for r in parsed.records):
            parsed.errors.append(f"Missing {kind}")
    if parsed.records and parsed.records[-1].kind != "TAIL":
        parsed.errors.append("TAIL must be last")
    from .hvac import hvac_errors
    parsed.errors.extend(hvac_errors(parsed))
    return parsed
