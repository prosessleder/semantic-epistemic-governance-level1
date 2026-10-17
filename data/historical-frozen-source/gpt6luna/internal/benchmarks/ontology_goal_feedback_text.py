"""Readable execution diagnostics; never generate or choose an ontology edit."""
import json


def render_states(states, proposal=None):
    lines = []
    for index, item in enumerate(states, 1):
        g = item["goal"]
        profile = "{" + ", ".join(g["profile"]) + "}"
        lines.append(f"Check {index}: {'PASS' if item['passed'] else 'FAIL'}. Supplied facts {profile}: "
            f"{g['kind']} {g['target']} must be {g['expected']}; computed value is {item['actual']}.")
        lines.append("Available classifications: " + ", ".join(item["derived_classes"]))
        lines.append("Effective permissions: " + ", ".join(item["effective_permissions"]))
        if item["inconsistent_pairs"]:
            lines.append("Conflicts still present: " + repr(item["inconsistent_pairs"])
                + ". Effective permissions stay empty while these conflicts remain.")
        if proposal and not item["passed"] and g["expected"]:
            if proposal.get("op") == "add_rule":
                needed = proposal["antecedents"]
            elif proposal.get("op") == "add_edge":
                needed = [proposal["left"]]
            else:
                needed = []
            missing = sorted(set(needed) - set(item["derived_classes"]))
            if missing:
                lines.append("The proposed relationship CANNOT activate for this required profile: "
                    + ", ".join(missing) + " is absent even after applying the edit. "
                    "An AND rule requires every antecedent. Fix this failed profile as well as the others.")
    return "\n".join(lines)


def render_attempts(attempts):
    lines = []
    for index, attempt in enumerate(attempts, 1):
        lines.append(f"Attempt {index}, proposed edit: " + json.dumps(attempt['proposal'],sort_keys=True,allow_nan=False))
        d = attempt["diagnostic"]
        if attempt["parse_error"]:
            lines.append("Response framing failed: " + attempt["parse_error"])
        if d["status"] == "invalid-edit":
            lines.append("Invalid edit: " + d["error"])
        elif d["status"] == "abstained":
            lines.append("Abstention has a certified empty-profile obstruction." if d.get("impossibility_certified",False)
                else "Abstention has NO certified obstruction. Adding a new AND rule with existing classes is allowed.")
        else:
            lines.append(render_states(d["goal_states"], attempt["proposal"]))
    return "\n".join(lines)
