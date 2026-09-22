from prereq import parse_requirement

def test_single_and_empty():
    assert parse_requirement("MATH105").groups == ((("MATH105", "pre"),),)
    for empty in ("", None, float("nan"), "None"):
        assert parse_requirement(empty).is_empty

def test_corequisite_tag():
    req = parse_requirement("CSBP121, CSBP219 (co)")
    assert req.groups == ((("CSBP121", "pre"),), (("CSBP219", "co"),))

def test_co_slash_pre_is_not_split_as_or():
    req = parse_requirement("CENG205 (co/pre) & PHYS105")
    assert req.groups == ((("CENG205", "co"),), (("PHYS105", "pre"),))

def test_or_group():
    req = parse_requirement("ITBP301 or ITBP280")
    assert len(req.groups) == 1 and {c for c, _ in req.groups[0]} == {"ITBP301", "ITBP280"}

def test_credit_hours_rule():
    req = parse_requirement("Minimum 80 completed credit hours")
    assert req.min_credits == 80 and not req.groups

def test_unparseable_text_never_blocks():
    req = parse_requirement("Junior standing")
    assert req.is_empty is True or (not req.groups and req.min_credits == 0)
    assert req.notes == ("Junior standing",)

def test_spaces_and_case():
    assert parse_requirement("csbp 219 and isec 311").groups == ((("CSBP219", "pre"),), (("ISEC311", "pre"),))
