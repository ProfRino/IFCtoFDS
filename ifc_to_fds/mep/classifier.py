"""Prefer explicit IFC type/system semantics to names."""

import unicodedata
import re


def semantic_label(value):
    text = unicodedata.normalize("NFKD", str(value or "")).casefold().replace("đ", "d")
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[\W_]+", " ", text).strip()


# Exact declared IfcSystem.ObjectType vocabulary. These rules never inspect a
# product/system Name or guess from a substring such as SPR/FP/SMOKE.
SYSTEM_OBJECT_TYPES = {
    "he thong chua chay sprinkler": "FIRE_SUPPRESSION",
    "fp he thong chua chay sprinkler": "FIRE_SUPPRESSION",
    "he thong tang ap": "SMOKE_EXTRACT",
    "he thong hut khoi": "SMOKE_EXTRACT",
    "he thong thong gio bai do xe": "VENTILATION",
    "he thong cap gio tuoi": "VENTILATION",
    "he thong thong gio ve sinh": "VENTILATION",
    "m return air": "VENTILATION",
    "return air": "VENTILATION",
    "supply air": "VENTILATION",
}

HVAC_TYPES = {
    "IFCDUCTSEGMENT",
    "IFCDUCTFITTING",
    "IFCAIRTERMINAL",
    "IFCAIRTERMINALBOX",
    "IFCDUCTSILENCER",
    "IFCFAN",
    "IFCDAMPER",
}
MEP_TYPES = HVAC_TYPES | {
    "IFCFLOWMOVINGDEVICE",
    "IFCFLOWCONTROLLER",
    "IFCPIPESEGMENT",
    "IFCPIPEFITTING",
    "IFCVALVE",
    "IFCPUMP",
    "IFCFIRESUPPRESSIONTERMINAL",
    "IFCFLOWSEGMENT",
    "IFCFLOWFITTING",
    "IFCFLOWTERMINAL",
    "IFCUNITARYEQUIPMENT",
    "IFCSENSOR",
    "IFCALARM",
    "IFCFLOWINSTRUMENT",
    "IFCDISTRIBUTIONCONTROLELEMENT",
    "IFCDISTRIBUTIONELEMENT",
    "IFCDISTRIBUTIONFLOWELEMENT",
    "IFCDISTRIBUTIONCHAMBERELEMENT",
}


def classify_mep_element(
    ifc_type,
    name,
    system_name="",
    predefined_type="",
    type_class="",
    property_sets=None,
    system_categories=(),
    object_type="",
):
    t = (type_class or ifc_type or "").upper()
    if t.endswith("TYPE"):
        t = t[:-4]
    p = str(predefined_type or "").upper()
    if t == "IFCFIRESUPPRESSIONTERMINAL":
        return "FIRE_SUPPRESSION", True
    enum_categories = {
        "FIRE_SUPPRESSION": {
            "FIREPROTECTION",
            "FIRE PROTECTION",
            "FIRE_SUPPRESSION",
            "SPRINKLER",
            "FIREHYDRANT",
        },
        "SMOKE_EXTRACT": {
            "SMOKEEXHAUST",
            "SMOKE EXTRACT",
            "SMOKECONTROL",
            "PRESSURISATION",
            "PRESSURIZATION",
        },
        "VENTILATION": {"VENTILATION", "AIRCONDITIONING", "EXHAUST"},
        "PLUMBING": {
            "DOMESTICCOLDWATER",
            "DOMESTICHOTWATER",
            "DRAINAGE",
            "SEWAGE",
            "WATERSUPPLY",
        },
    }

    def result(category):
        # A duct/fan class cannot establish a water/fire-suppression function.
        if t in HVAC_TYPES and category in ("FIRE_SUPPRESSION", "PLUMBING"):
            return "UNRESOLVED", False
        return category, category in ("FIRE_SUPPRESSION", "SMOKE_EXTRACT")

    declared = {
        category
        for category, values in enum_categories.items()
        if p in values
        or (
            object_type
            and semantic_label(object_type) in {semantic_label(v) for v in values}
        )
    }
    if semantic_label(object_type) in SYSTEM_OBJECT_TYPES:
        declared.add(SYSTEM_OBJECT_TYPES[semantic_label(object_type)])
    if len(declared) > 1:
        return "UNRESOLVED", False
    if declared:
        return result(next(iter(declared)))

    def resolve_category(cat):
        if cat in enum_categories:
            return cat
        for enum_cat, values in enum_categories.items():
            if cat in values:
                return enum_cat
        return cat

    categories = {
        resolve_category(x)
        for x in system_categories
        if x not in ("OTHER", "UNRESOLVED")
    }
    if len(categories) > 1:
        return "UNRESOLVED", False
    if categories:
        return result(next(iter(categories)))
    explicit_property_values = []
    for properties in (property_sets or {}).values():
        if isinstance(properties, dict):
            explicit_property_values.extend(
                str(value).upper()
                for key, value in properties.items()
                if key.replace(" ", "").lower()
                in ("systemtype", "systemclassification", "servicetype")
            )
    categories = {
        category
        for category, values in enum_categories.items()
        if any(v in values for v in explicit_property_values)
    }
    if len(categories) > 1:
        return "UNRESOLVED", False
    if categories:
        return result(next(iter(categories)))
    if t in HVAC_TYPES:
        return "VENTILATION", False
    return "UNRESOLVED", False
