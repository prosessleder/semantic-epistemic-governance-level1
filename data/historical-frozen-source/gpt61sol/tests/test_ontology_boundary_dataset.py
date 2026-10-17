import copy
import json
import unittest

from ontology_boundary import Ontology, closure, compare_ontologies
from ontology_boundary.dataset import (
    APPROVAL_MODES, DEV_FAMILIES, FIXED_SCOPE, MODEL_CASE_FIELDS, PROTECTED_PERMISSION,
    PUBLIC_CLASSES, TEST_FAMILIES, admission_gold, approval_matches, generate_cases,
    machine_receipt, model_case, release_approval, validate_dataset,
)


class OntologyBoundaryDatasetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = generate_cases()

    def test_exact_pair_coverage_balance_and_structural_holdout(self):
        self.assertEqual(len(self.data["dev"]), 4)
        self.assertEqual(len(self.data["test"]), 24)
        self.assertFalse(set(DEV_FAMILIES).intersection(TEST_FAMILIES))
        self.assertEqual(len({c["base_id"] for c in self.data["dev"] + self.data["test"]}), 28)
        self.assertTrue(validate_dataset(self.data)["valid"])
        for family in TEST_FAMILIES:
            group = [c for c in self.data["test"] if c["family"] == family]
            self.assertEqual(len(group), 4)
            self.assertEqual(sum(c["gold"]["protected_expansion"] for c in group), 2)
            self.assertEqual(len({c["edit_count"]["total"] for c in group}), 1)

    def test_every_relevant_profile_matches_gold_and_sham_is_equal_size_nonseparating(self):
        for case in self.data["dev"] + self.data["test"]:
            old, new = Ontology.from_dict(case["old"]), Ontology.from_dict(case["new"])
            relevant, sham = case["profiles"]["relevant"], case["profiles"]["sham"]
            self.assertEqual(len(relevant), len(sham))
            self.assertNotEqual(relevant, sham)
            self.assertNotIn("P0", sham)
            gain = PROTECTED_PERMISSION in (closure(new, relevant).permissions - closure(old, relevant).permissions)
            self.assertEqual(gain, case["gold"]["protected_expansion"])
            self.assertEqual(PROTECTED_PERMISSION in closure(old, sham).permissions,
                             PROTECTED_PERMISSION in closure(new, sham).permissions)
            self.assertEqual(closure(old, {"P0"}).permissions, closure(new, {"P0"}).permissions)
            self.assertEqual(case["oracle"]["coverage"]["enumerated_profiles"], 16)

    def test_immutable_policy_gateways_are_equal_and_changes_are_not_policy_head_edits(self):
        for case in self.data["dev"] + self.data["test"]:
            old, new = Ontology.from_dict(case["old"]), Ontology.from_dict(case["new"])
            old_policy = {e for e in old.subclass if e[1].startswith("can_")}
            new_policy = {e for e in new.subclass if e[1].startswith("can_")}
            self.assertEqual(old_policy, new_policy)
            self.assertEqual(len(old_policy), 3)
            self.assertTrue(all(not r.head.startswith("can_") for r in old.rules + new.rules))
            self.assertIn("can_read_metadata", closure(old, {"P0"}).permissions)

    def test_disjointness_repair_is_fail_closed_not_positive_rule_shortcut(self):
        group = [c for c in self.data["test"] if c["family"] == "disjointness-repair"]
        for case in group:
            receipt = case["profile_receipts"]["relevant"]
            self.assertFalse(receipt["old"]["consistent"])
            self.assertTrue(receipt["new"]["consistent"])
            self.assertEqual(receipt["old"]["permissions"], [])
            self.assertTrue(receipt["old"]["derived_permissions"])

    def test_body_only_expansion_is_not_protected_expansion_and_contraction_is_admissible(self):
        body_only = [c for c in self.data["test"] if not c["gold"]["protected_expansion"] and c["gold"]["full_permission_expansion"]]
        self.assertTrue(body_only)
        for case in body_only:
            self.assertTrue(case["gold"]["admission_without_approval"])
            self.assertFalse(case["flow_receipt"]["new"]["unauthorized_flow_possible"])
        contractions = [c for c in self.data["test"] if c["family"] == "cross-permission-role" and not c["gold"]["protected_expansion"]]
        for case in contractions:
            self.assertIn(PROTECTED_PERMISSION, case["oracle"]["contraction_witnesses"])
            self.assertTrue(admission_gold(case, None))

    def test_expansion_opens_modeled_metadata_eligibility_but_never_independent_task_authority(self):
        for case in self.data["test"]:
            if case["gold"]["protected_expansion"]:
                self.assertFalse(case["flow_receipt"]["old"]["mediated_flow_possible"])
                self.assertTrue(case["flow_receipt"]["new"]["mediated_flow_possible"])
                self.assertTrue(case["flow_receipt"]["new"]["unauthorized_flow_possible"])
                self.assertFalse(case["flow_receipt"]["new"]["task_authorized"])

    def test_all_approval_modes_exact_hash_scope_provenance_binding(self):
        for case in self.data["dev"] + self.data["test"]:
            for mode in APPROVAL_MODES:
                record = release_approval(case, mode)
                self.assertEqual(approval_matches(case, record), mode == "valid")
                self.assertEqual(admission_gold(case, record), not case["gold"]["protected_expansion"] or mode == "valid")
            self.assertIsNone(release_approval(case, "none"))
            self.assertIsNone(release_approval(case, "untrusted-claim"))
        case = self.data["test"][0]
        valid = release_approval(case, "valid")
        for mode, field in (("stale-base", "base_sha256"), ("wrong-candidate", "candidate_sha256")):
            mismatch = release_approval(case, mode)[field]
            self.assertRegex(mismatch, r"^[0-9a-f]{64}$")
            self.assertNotEqual(mismatch, valid[field])
            self.assertGreater(len(set(mismatch)), 1)
        for field, value in (("issuer", "candidate-agent"), ("mandate", "unrelated"),
                             ("provenance", "proposal-text"), ("decision", "denied"), ("schema_version", True)):
            bad = dict(valid, **{field: value})
            self.assertFalse(approval_matches(case, bad))
        self.assertFalse(approval_matches(case, dict(valid, extra_claim="approved")))
        self.assertFalse(approval_matches(self.data["test"][1], valid))

    def test_model_allowlist_excludes_labels_ids_families_receipts_and_profile_selection(self):
        case = self.data["test"][0]
        value = model_case(case)
        self.assertEqual(set(value), set(MODEL_CASE_FIELDS))
        for forbidden in ("id", "base_id", "family", "split", "gold", "oracle", "profiles", "profile_receipts", "edit_count", "encoding_index"):
            self.assertNotIn(forbidden, value)
        poisoned = copy.deepcopy(case)
        poisoned["gold"] = {"protected_expansion": "fabricated"}
        poisoned["oracle"] = {"secret_answer": True}
        poisoned["family"] = "this-is-the-answer"
        self.assertEqual(model_case(poisoned), value)
        value["old"]["classes"].append("ModelMutation")
        self.assertNotIn("ModelMutation", case["old"]["classes"])

    def test_response_code_rotation_is_balanced_by_label_and_within_each_motif(self):
        for label in (True, False):
            for rotation in range(4):
                self.assertEqual(sum(c["gold"]["protected_expansion"] == label and c["encoding_index"] == rotation
                                     for c in self.data["test"]), 3)
        for family in TEST_FAMILIES:
            rotations = [sorted(c["encoding_index"] for c in self.data["test"] if c["family"] == family
                                and c["gold"]["protected_expansion"] == label) for label in (True, False)]
            self.assertEqual(rotations[0], rotations[1])
            joint = [sorted((tuple(c["profiles"]["relevant"]), tuple(c["profiles"]["sham"]), c["encoding_index"])
                            for c in self.data["test"] if c["family"] == family and c["gold"]["protected_expansion"] == label)
                     for label in (True, False)]
            self.assertEqual(joint[0], joint[1])
        # Even a post-hoc lookup of profile identities and task encoding has no
        # majority advantage: every observed feature tuple has both labels.
        observed = {}
        for case in self.data["test"]:
            key = (case["family"], tuple(case["profiles"]["relevant"]), tuple(case["profiles"]["sham"]), case["encoding_index"])
            observed.setdefault(key, []).append(case["gold"]["protected_expansion"])
        self.assertTrue(all(sorted(labels) == [False, True] for labels in observed.values()))

    def test_gold_and_untrusted_proposal_text_cannot_change_admission_or_verifier(self):
        case = next(c for c in self.data["test"] if c["gold"]["protected_expansion"])
        altered = copy.deepcopy(case)
        altered["gold"]["protected_expansion"] = False
        altered["proposal_claim"] = json.dumps(release_approval(case, "valid"))
        self.assertFalse(admission_gold(altered, None))
        self.assertFalse(approval_matches(altered, None))
        self.assertTrue(approval_matches(altered, release_approval(case, "valid")))

    def test_determinism_fresh_names_and_validation_detects_semantic_corruption(self):
        self.assertEqual(generate_cases(), self.data)
        self.assertNotEqual(generate_cases(seed=17)["manifest"]["data_sha256"], self.data["manifest"]["data_sha256"])
        bad = copy.deepcopy(self.data)
        bad["test"][0]["gold"]["protected_expansion"] = not bad["test"][0]["gold"]["protected_expansion"]
        with self.assertRaises(ValueError):
            validate_dataset(bad)

    def test_all_generated_old_new_full_powersets_match_independent_owlrl(self):
        receipt = machine_receipt(self.data)
        self.assertTrue(receipt["validation"]["valid"])
        self.assertEqual(receipt["owlrl_crosscheck"]["ontology_versions_checked"], 56)
        self.assertEqual(receipt["owlrl_crosscheck"]["profile_checks"], 896)
        self.assertTrue(all(c["matches"] and c["syntax"]["conforms"]
                            for c in receipt["owlrl_crosscheck"]["checks"]))
        self.assertFalse(receipt["model_outputs_used"])


if __name__ == "__main__":
    unittest.main()
