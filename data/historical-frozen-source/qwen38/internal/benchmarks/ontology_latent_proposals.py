"""Permission expansions outside both current and mission-goal profiles."""
import random
from ontology_boundary.checked_release import Goal, ReviewContract, apply_proposal, goals_satisfied
from ontology_boundary.oracle import Ontology, HornRule
from internal.scripts.audit_ontology_boundary_robustness import independent_state

FAMILIES = ("latent-body-edge", "latent-body-bridge", "latent-disjointness-repair")


def probed_expansion(contract, candidate):
    profiles = set(contract.current_profiles) | {g.profile for g in contract.goals}
    return any(independent_state(candidate.to_dict(), p, contract.protected_permission)["effective"]
               and not independent_state(contract.base.to_dict(), p, contract.protected_permission)["effective"]
               for p in profiles)


def tasks(seed=2026101207):
    result = []
    for fi, family in enumerate(FAMILIES):
        for slot in range(4):
            helpers = [f"H{i}" for i in range(7)]
            random.Random(seed + fi * 101 + slot).shuffle(helpers)
            gm, gb, gr, h0, h1, h2, h3 = helpers
            r, s = f"P{1 + slot % 3}", f"P{1 + (slot + 1) % 3}"
            public = frozenset({"P0", "P1", "P2", "P3"})
            edges = [(gm, "can_write_metadata"), (gb, "can_write_body"),
                     (gr, "can_read_metadata"), ("P0", gr)]
            # The permission head is immutable. The conjunction's class head
            # makes a body-enabling change also enable metadata for a future actor.
            rules = (HornRule(frozenset({gb, s}), gm),)
            disjoint = ()
            if family == "latent-body-edge":
                goals = (Goal(frozenset({r}), "effective", "can_write_body"),)
                patch = dict(op="add_edge", left=r, right=gb)
            elif family == "latent-body-bridge":
                edges += [(r, h0), (h1, gb)]
                goals = (Goal(frozenset({r}), "class", h1),)
                patch = dict(op="add_edge", left=h0, right=h1)
            else:
                edges += [(r, h0), (r, gb)]
                disjoint = ((r, h0),)
                goals = (Goal(frozenset({r}), "effective", "can_write_body"),
                         Goal(frozenset({r}), "class", h0))
                patch = dict(op="remove_disjoint", left=r, right=h0)
            base = Ontology(public | frozenset(helpers), tuple(edges), rules, disjoint)
            contract = ReviewContract(base, public, "can_write_metadata", goals)
            candidate = apply_proposal(contract, patch)
            assert not goals_satisfied(contract, base) and goals_satisfied(contract, candidate)
            witness = frozenset({r, s})
            assert not independent_state(base.to_dict(), witness, contract.protected_permission)["effective"]
            assert independent_state(candidate.to_dict(), witness, contract.protected_permission)["effective"]
            assert witness not in {g.profile for g in goals} | set(contract.current_profiles)
            assert not probed_expansion(contract, candidate)
            result.append(dict(task_id=f"latent-{fi:02d}-{slot}", family=family, contract=contract.to_dict(),
                reference_patch=patch, reference_candidate=candidate.to_dict(), reference_witness=sorted(witness)))
    return result
