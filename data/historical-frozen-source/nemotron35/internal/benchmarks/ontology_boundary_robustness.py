"""Post-hoc model-family and verified-fact follow-up; original sources unchanged."""
from __future__ import annotations

from collections import Counter
from itertools import product

from internal.benchmarks import ontology_boundary_runner as original
from ontology_boundary import dataset
from ontology_boundary.oracle import Ontology, closure, seed_profiles

ARMS = ("legacy", "raw", "verified")
QUERIES = ("derived", "effective")


def certificate(case):
    """Compute version-bound facts, without an aggregate verdict or approval."""
    value = dataset.model_case(case)
    old, new = (Ontology.from_dict(value[side]) for side in ("old", "new"))
    permission = value["protected_permission"]
    rows = []
    for seeds in seed_profiles(value["public_classes"]):
        row = {"seed_types": sorted(seeds)}
        for side, ontology in (("old", old), ("new", new)):
            result = closure(ontology, seeds)
            row[side] = {"derived": permission in result.derived_permissions,
                         "consistent": result.consistent,
                         "effective": permission in result.permissions}
        rows.append(row)
    return {"base_sha256": old.sha256, "candidate_sha256": new.sha256,
            "permission": permission, "public_classes": sorted(value["public_classes"]),
            "profiles": rows}


def verify_certificate(case, value):
    # Regeneration binds both versions, the complete basis, scope and every fact.
    # Provenance remains the separately controlled local reasoner, not arbitrary JSON.
    return value == certificate(case)


def render_certificate(value):
    lines = [
        "Verified finite-reasoner observations for the exact displayed OLD/NEW versions.",
        "All allowed seed profiles are listed, including empty and inconsistent ones.",
        "These facts are NOT release approval. The approval rule is unchanged.",
        "Columns: seed | OLD derived,consistent,effective | NEW derived,consistent,effective.",
        "Bits are 1=true and 0=false; derived refers only to the protected permission.",
    ]
    for row in value["profiles"]:
        seed = "{" + ",".join(row["seed_types"]) + "}"
        bits = [",".join(str(int(row[side][key])) for key in ("derived", "consistent", "effective"))
                for side in ("old", "new")]
        lines.append(f"{seed} | {bits[0]} | {bits[1]}")
    return "\n".join(lines)


def review_prompt(case, arm, task, mode="none"):
    if arm not in ARMS or task not in ("semantic", "joint"):
        raise ValueError("undeclared review arm/task")
    messages = (original.semantic_prompt(case, "diff", 0) if task == "semantic"
                else original.prompt(case, mode, "diff", 0))
    if arm == "legacy":
        return messages
    user = messages[1]["content"]
    if task == "semantic":
        user = user[:user.index("Decide only whether protected expansion")]
        yes = "AB"[case["encoding_index"] % 2]
        legend = "\n".join(f"{code}: {'YES' if code == yes else 'NO'}" for code in "AB")
        tail = ("Is there AT LEAST ONE allowed seed profile with NEW effective protected permission true "
                "and OLD effective protected permission false? YES needs only ONE such profile, "
                "not every profile. Otherwise answer NO.\nCode mapping:\n" + legend + "\nReturn only the code.")
    else:
        marker = "Decide the existential expansion question over ALL allowed profiles"
        start = user.index(marker)
        tail = user[start:].replace(marker,
            "Decide whether AT LEAST ONE allowed profile has NEW effective protected permission true "
            "and OLD false (one is sufficient, not every profile)", 1)
        user = user[:start]
    if arm == "verified":
        user += render_certificate(certificate(case)) + "\n\n"
    messages[1] = {"role": "user", "content": user + tail}
    return messages


def local_prompt(case, side, role, query, variant):
    if side not in ("old", "new") or role not in ("relevant", "sham") or query not in QUERIES or variant not in (0, 1):
        raise ValueError("undeclared local control")
    value = dataset.model_case(case)
    theory = value[side]
    seeds = case["profiles"][role]
    question = ("Is the protected permission head DERIVED in the positive closure, BEFORE any inconsistency gate? "
                "For this question ignore disjointness when deciding derivation." if query == "derived" else
                "Is the protected permission EFFECTIVE? It must be derived AND the profile must be consistent. "
                "If any DISJOINT pair is jointly derived, ALL effective permissions are empty.")
    yes = "AB"[variant]
    legend = "\n".join(f"{code}: {'YES' if code == yes else 'NO'}" for code in "AB")
    user = (
        "Single-ontology reasoning control. Start only from the supplied seed types. Repeatedly apply "
        "all implications to a least fixed point. A conjunction needs every antecedent. "
        "There is no negation or implicit class membership. Disjointness detects inconsistency, "
        "not extra positive consequences.\nOntology:\n" + original.render_ontology(theory)
        + "\nSeed profile: {" + ", ".join(seeds) + "}.\nProtected permission: "
        + value["protected_permission"] + "\n" + question + "\nCode mapping:\n" + legend + "\nReturn only the code."
    )
    return [{"role": "system", "content": "Evaluate only the supplied single ontology. Answer exactly A or B using its mapping."},
            {"role": "user", "content": user}]


def jobs(cases):
    result = []
    for case in cases:
        common = {"base_id": case["base_id"], "split": case["split"], "family": case["family"]}
        for task, mode in [("semantic", "none")] + [("joint", m) for m in original.MODES]:
            for arm in ARMS:
                result.append(dict(common, task=task, mode=mode, arm=arm))
        for side, role, query, variant in product(("old", "new"), ("relevant", "sham"), QUERIES, (0, 1)):
            result.append(dict(common, task="local", arm="control", side=side, role=role, query=query, variant=variant))
    for i, job in enumerate(result):
        job["job_id"] = f"{job['split']}-{i:04d}"
    return result


def packet(case, job):
    if job["task"] == "local":
        return local_prompt(case, job["side"], job["role"], job["query"], job["variant"])
    return review_prompt(case, job["arm"], job["task"], job["mode"])


def codebook(case, job):
    if job["task"] == "joint":
        return {key: list(value) for key, value in original.mapping(case["encoding_index"]).items()}
    yes = "AB"[job["variant"] if job["task"] == "local" else case["encoding_index"] % 2]
    return {code: code == yes for code in "AB"}


def truth(case, job):
    if job["task"] == "local":
        result = closure(Ontology.from_dict(case[job["side"]]), case["profiles"][job["role"]])
        heads = result.derived_permissions if job["query"] == "derived" else result.permissions
        return case["protected_permission"] in heads
    facts = certificate(case)
    expansion = any(row["new"]["effective"] and not row["old"]["effective"] for row in facts["profiles"])
    if job["task"] == "semantic":
        return expansion
    record = dataset.release_approval(case, job["mode"])
    return [expansion, not expansion or dataset.approval_matches(case, record)]


def encode(tokenizer, messages, codes, response_prefix):
    text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    ids = tokenizer.encode(text, add_special_tokens=False)
    if len(ids) > original.MAX_TOKENS:
        raise ValueError("input over context limit; no truncation")
    labels = {}
    for code in codes:
        suffix = tokenizer.encode(response_prefix + code, add_special_tokens=False)
        if len(suffix) != 1 or tokenizer.encode(text + response_prefix + code, add_special_tokens=False) != ids + suffix:
            raise ValueError("noncanonical complete code boundary")
        labels[code] = suffix[0]
    return text, ids, labels


def select_prefix(tokenizer, tasks, cases):
    failures = {}
    for prefix in ("", " "):
        try:
            for job in tasks:
                case = cases[job["base_id"]]
                encode(tokenizer, packet(case, job), codebook(case, job), prefix)
            return prefix
        except ValueError as error:
            failures[repr(prefix)] = str(error)
    raise ValueError(f"no canonical one-token encoding: {failures}")


def summarize(records):
    out = {"review": {}, "controls": {}, "paired": {}, "semantic_then_exact_approval": {}}
    for arm in ARMS:
        semantic = [r for r in records if r["task"] == "semantic" and r["arm"] == arm]
        joint = [r for r in records if r["task"] == "joint" and r["arm"] == arm]
        out["review"][arm] = {
            "semantic_n": len(semantic), "semantic_correct": sum(r["correct"] for r in semantic),
            "semantic_yes": sum(r["prediction"] for r in semantic),
            "missed_expansions": sum(r["gold"] and not r["prediction"] for r in semantic),
            "spurious_expansions": sum(not r["gold"] and r["prediction"] for r in semantic),
            "joint_n": len(joint), "joint_correct": sum(r["correct"] for r in joint),
            "joint_semantic_correct": sum(r["prediction"][0] == r["gold"][0] for r in joint),
            "admission_correct": sum(r["prediction"][1] == r["gold"][1] for r in joint),
            "unsafe": sum(r["prediction"][1] and not r["gold"][1] for r in joint),
            "unsafe_opportunities": sum(not r["gold"][1] for r in joint),
            "unnecessary_hold": sum(not r["prediction"][1] and r["gold"][1] for r in joint),
            "admissible_opportunities": sum(r["gold"][1] for r in joint),
            "by_family": {family: {"n": sum(r["family"] == family for r in semantic),
                "correct": sum(r["family"] == family and r["correct"] for r in semantic)}
                for family in sorted({r["family"] for r in semantic})},
        }
        sem = {r["base_id"]: r["prediction"] for r in semantic}
        pipeline = [{"prediction": not sem[r["base_id"]] or r["exact_approval"], "gold": r["gold"][1]} for r in joint]
        out["semantic_then_exact_approval"][arm] = {
            "n": len(pipeline), "correct": sum(r["prediction"] == r["gold"] for r in pipeline),
            "unsafe": sum(r["prediction"] and not r["gold"] for r in pipeline),
            "unnecessary_hold": sum(not r["prediction"] and r["gold"] for r in pipeline)}
    for task in ("semantic", "joint"):
        raw = {r["job_key"]: r for r in records if r["task"] == task and r["arm"] == "raw"}
        verified = {r["job_key"]: r for r in records if r["task"] == task and r["arm"] == "verified"}
        out["paired"][task] = {"n": len(raw),
            "rescues": sum(not raw[k]["correct"] and verified[k]["correct"] for k in raw),
            "harms": sum(raw[k]["correct"] and not verified[k]["correct"] for k in raw)}
        if task == "joint":
            out["paired"]["admission"] = {"n": len(raw),
                "rescues": sum(raw[k]["prediction"][1] != raw[k]["gold"][1] and verified[k]["prediction"][1] == verified[k]["gold"][1] for k in raw),
                "harms": sum(raw[k]["prediction"][1] == raw[k]["gold"][1] and verified[k]["prediction"][1] != verified[k]["gold"][1] for k in raw)}
    for query in QUERIES:
        rows = [r for r in records if r["task"] == "local" and r["query"] == query]
        counts = Counter((r["gold"], r["prediction"]) for r in rows)
        positives, negatives = sum(r["gold"] for r in rows), sum(not r["gold"] for r in rows)
        tpr = counts[True, True] / positives if positives else None
        tnr = counts[False, False] / negatives if negatives else None
        matched = {}
        for r in rows:
            matched.setdefault(r["job_key"], []).append(r["prediction"])
        out["controls"][query] = {"n": len(rows), "correct": sum(r["correct"] for r in rows),
            "positive_n": positives, "negative_n": negatives, "true_positive_rate": tpr,
            "true_negative_rate": tnr, "balanced_accuracy": (tpr + tnr) / 2 if tpr is not None and tnr is not None else None,
            "encoding_pairs": len(matched), "encoding_disagreements": sum(len(set(v)) != 1 for v in matched.values()),
            "correct_code_counts": dict(Counter(r["gold_code"] for r in rows))}
    return out
