import json
import unittest

from ontology_boundary import (
    CLASS_NAMESPACE, POLICY_NAMESPACE, ExternalGrant, HornRule, Ontology,
    closure, compare_flow_eligibility, compare_ontologies, crosscheck_ontology,
    crosscheck_profile, flow_decision, ontology_from_rdf, ontology_to_rdf,
    parse_ontology, seed_profiles, validate_rdf_syntax,
)


class FiniteOracleTests(unittest.TestCase):
    def test_dormant_expansion_with_unchanged_current_and_empty_probes(self):
        old = Ontology({"Active", "Dormant", "Writer"})
        new = Ontology(old.classes, (("Dormant", "Writer"), ("Writer", "can_write_metadata")))
        result = compare_ontologies(old, new, {"Active", "Dormant"}, current_probes=[{"Active"}])
        self.assertEqual(result["coverage"]["enumerated_profiles"], 4)
        self.assertTrue(result["current_probes_unchanged"])
        self.assertTrue(result["empty_probe_unchanged"])
        self.assertEqual(result["expansion_witnesses"], {"can_write_metadata": [["Dormant"]]})
        self.assertEqual(result["affected_fields"], ["metadata"])
        self.assertFalse(result["universal_owl_claim"])

    def test_conjunction_requires_two_seed_types_and_returns_all_minimal_witnesses(self):
        old = Ontology({"A", "B", "C", "D"})
        new = Ontology(old.classes, rules=(HornRule({"A", "B"}, "can_write_body"),
                                          HornRule({"C", "D"}, "can_write_body")))
        result = compare_ontologies(old, new, old.classes)
        self.assertEqual(result["expansion_witnesses"]["can_write_body"], [["A", "B"], ["C", "D"]])
        self.assertEqual(closure(new, {"A"}).permissions, frozenset())
        self.assertEqual(closure(new, {"A", "B", "C"}).permissions, {"can_write_body"})

    def test_intermediate_helper_and_alias_refactors_preserve_public_permission_signature(self):
        old = Ontology({"A", "B"}, (("A", "B"), ("B", "can_read_metadata")))
        new = Ontology({"A", "B", "Helper"}, (("A", "Helper"), ("Helper", "B"),
                                               ("B", "can_read_metadata")))
        self.assertTrue(compare_ontologies(old, new, {"A", "B"})["permission_preserving"])
        alias = Ontology({"A", "B", "Helper"}, (("A", "Helper"), ("Helper", "A"),
                                                 ("Helper", "B"), ("B", "can_read_metadata")))
        self.assertTrue(compare_ontologies(old, alias, {"A", "B"})["permission_preserving"])
        with self.assertRaises(ValueError):
            compare_ontologies(old, new, {"A", "Helper"})

    def test_unrelated_axiom_does_not_create_authorization_and_removal_contracts(self):
        old = Ontology({"A", "B", "X", "Y"}, (("A", "B"), ("B", "can_read_body")))
        irrelevant = Ontology(old.classes, old.subclass + (("X", "Y"),))
        self.assertTrue(compare_ontologies(old, irrelevant, old.classes)["permission_preserving"])
        contraction = Ontology(old.classes, (("A", "B"),))
        result = compare_ontologies(old, contraction, {"A", "B"})
        self.assertTrue(result["no_expansion"])
        self.assertEqual(result["contraction_witnesses"], {"can_read_body": [["A"], ["B"]]})

    def test_inconsistency_fails_closed_but_repair_is_an_effective_expansion(self):
        old = Ontology({"A", "B"}, (("A", "B"), ("A", "can_write_body")), disjoint=(("A", "B"),))
        bad = closure(old, {"A"})
        self.assertFalse(bad.consistent)
        self.assertEqual(bad.derived_permissions, {"can_write_body"})
        self.assertEqual(bad.permissions, frozenset())
        new = Ontology(old.classes, old.subclass)
        result = compare_ontologies(old, new, {"A", "B"})
        self.assertEqual(result["expansion_witnesses"], {"can_write_body": [["A"]]})
        row = next(x for x in result["profiles"] if x["seed_types"] == ["A"])
        self.assertFalse(row["old"]["consistent"])
        self.assertTrue(row["new"]["consistent"])

    def test_cycles_terminate_and_class_absence_does_not_imply_negation(self):
        ontology = Ontology({"A", "B", "C"}, (("A", "B"), ("B", "A"), ("B", "can_read_body")))
        result = closure(ontology, {"A"})
        self.assertEqual(result.class_types, {"A", "B"})
        self.assertEqual(result.permissions, {"can_read_body"})
        self.assertEqual(closure(ontology, ()).permissions, frozenset())
        self.assertTrue(closure(ontology, ()).consistent)

    def test_ontology_schema_roundtrip_is_canonical_and_cannot_embed_gold_or_grants(self):
        original = Ontology({"B", "A"}, (("B", "A"),),
                            (HornRule({"A", "B"}, "can_read_body"),), (("B", "A"),))
        restored = Ontology.from_dict(json.loads(json.dumps(original.to_dict())))
        self.assertEqual(original, restored)
        self.assertEqual(original.sha256, restored.sha256)
        poisoned = dict(original.to_dict(), query_gold=True)
        with self.assertRaises(ValueError):
            Ontology.from_dict(poisoned)
        with self.assertRaises(ValueError):
            Ontology({"A"}, rules=(HornRule({"A"}, "external_approved_grant"),))
        with self.assertRaises(ValueError):
            closure(original, {"can_read_body"})
        with self.assertRaises(ValueError):
            HornRule((), "can_read_body")
        for malformed in (None, [], "not-an-object"):
            with self.assertRaises(ValueError):
                Ontology.from_dict(malformed)

    def test_complete_signature_cap_and_protected_query(self):
        self.assertEqual(len(seed_profiles([f"C{i}" for i in range(6)])), 64)
        with self.assertRaises(ValueError):
            seed_profiles([f"C{i}" for i in range(7)])
        old = Ontology({"A"})
        new = Ontology({"A"}, (("A", "can_write_body"),))
        result = compare_ontologies(old, new, {"A"}, protected_permissions={"can_read_metadata"})
        self.assertFalse(result["no_expansion"])
        self.assertTrue(result["protected_no_expansion"])
        with self.assertRaises(ValueError):
            compare_ontologies(old, new, {"A"}, current_probes=[{"Unknown"}])


class FlowOracleTests(unittest.TestCase):
    def setUp(self):
        self.ontology = Ontology({"Writer", "Reader"},
            (("Writer", "can_write_body"), ("Reader", "can_read_body"),
             ("Writer", "can_write_metadata"), ("Reader", "can_read_metadata")))
        self.writer = closure(self.ontology, {"Writer"})
        self.reader = closure(self.ontology, {"Reader"})

    def test_metadata_only_visible_foreign_task_is_possible_but_unauthorized(self):
        options = dict(source_task="task-A", destination_task="task-B", visibility={"body": False, "metadata": True})
        metadata = flow_decision(self.writer, self.reader, "metadata", **options)
        body = flow_decision(self.writer, self.reader, "body", **options)
        self.assertTrue(metadata["ontology_eligible"])
        self.assertTrue(metadata["mediated_flow_possible"])
        self.assertTrue(metadata["unauthorized_flow_possible"])
        self.assertFalse(metadata["authorized_flow_possible"])
        self.assertTrue(body["ontology_eligible"])
        self.assertFalse(body["mediated_flow_possible"])
        self.assertFalse(metadata["physical_channel_claim"])

    def test_same_task_and_exact_external_grant_are_distinct_and_field_scoped(self):
        same = flow_decision(self.writer, self.reader, "body", source_task="task-A", destination_task="task-A")
        self.assertTrue(same["authorized_flow_possible"])
        grant = ExternalGrant("g1", "source", "destination", "task-A", "task-B", {"metadata"}, True)
        options = dict(source_task="task-A", destination_task="task-B", external_grant=grant)
        self.assertTrue(flow_decision(self.writer, self.reader, "metadata", **options)["authorized_flow_possible"])
        self.assertFalse(flow_decision(self.writer, self.reader, "body", **options)["task_authorized"])
        self.assertFalse(flow_decision(self.writer, self.reader, "metadata", destination_agent="other", **options)["task_authorized"])
        denied = ExternalGrant("g1", "source", "destination", "task-A", "task-B", {"metadata"}, False)
        self.assertFalse(flow_decision(self.writer, self.reader, "metadata", source_task="task-A", destination_task="task-B", external_grant=denied)["task_authorized"])
        self.assertEqual(ExternalGrant.from_dict(grant.to_dict()), grant)
        with self.assertRaises(ValueError):
            flow_decision(self.writer, self.reader, "metadata", source_task="task-A", destination_task="task-B", external_grant={"approved": True})

    def test_future_joint_flow_witnesses_preserve_field_and_independent_roles(self):
        old = Ontology({"A", "B", "C"}, (("C", "can_read_metadata"),))
        new = Ontology(old.classes, old.subclass, (HornRule({"A", "B"}, "can_write_metadata"),))
        result = compare_flow_eligibility(old, new, {"A", "B", "C"}, source_task="A-task", destination_task="B-task",
                                         visibility={"body": False, "metadata": True}, current_probes=[({"C"}, {"C"})])
        self.assertEqual(result["coverage"]["profile_pairs"], 64)
        self.assertTrue(result["current_probes_unchanged"])
        self.assertEqual(set(result["expansion_witnesses"]), {"metadata"})
        witness = result["expansion_witnesses"]["metadata"][0]
        self.assertEqual(witness["source_seed_types"], ["A", "B"])
        self.assertEqual(witness["destination_seed_types"], ["C"])
        self.assertTrue(witness["new"]["unauthorized_flow_possible"])
        self.assertEqual(result["newly_possible_counts"]["metadata"], result["newly_unauthorized_counts"]["metadata"])

    def test_approval_cannot_supply_missing_permission_and_inconsistent_source_blocks_flow(self):
        grant = ExternalGrant("g", "source", "destination", "A", "B", {"body"}, True)
        empty = closure(self.ontology, ())
        result = flow_decision(empty, self.reader, "body", source_task="A", destination_task="B", external_grant=grant)
        self.assertTrue(result["task_authorized"])
        self.assertFalse(result["mediated_flow_possible"])
        inconsistent = Ontology({"Writer", "Reader"}, self.ontology.subclass, disjoint=(("Writer", "Reader"),))
        result = flow_decision(closure(inconsistent, {"Writer", "Reader"}), self.reader, "metadata", source_task="A", destination_task="A")
        self.assertFalse(result["mediated_flow_possible"])


class RestrictedRDFTests(unittest.TestCase):
    def test_owlrl_and_reference_agree_over_full_signature_with_conjunction_and_disjointness(self):
        ontology = Ontology({"A", "B", "C", "Helper"}, (("A", "Helper"), ("Helper", "C")),
            (HornRule({"B", "C"}, "can_write_metadata"), HornRule({"A"}, "can_read_body")), (("A", "B"),))
        result = crosscheck_ontology(ontology, {"A", "B", "C"})
        self.assertTrue(result["matches"])
        self.assertEqual(result["profiles_checked"], 8)
        self.assertFalse(result["syntax"]["authority_decision"])

    def test_rdf_roundtrip_and_supplied_turtle_only(self):
        ontology = Ontology({"A", "B"}, (("A", "can_read_body"),),
                            (HornRule({"A", "B"}, "can_write_metadata"),), (("A", "B"),))
        graph = ontology_to_rdf(ontology)
        self.assertEqual(ontology_from_rdf(graph), ontology)
        self.assertEqual(parse_ontology(graph.serialize(format="turtle")), ontology)
        with self.assertRaises(ValueError):
            parse_ontology("https://example.com/ontology", format="json-ld")
        self.assertTrue(crosscheck_profile(ontology, {"A", "B"})["matches"])
        with self.assertRaises(ValueError):
            crosscheck_profile(ontology, "AB")

    def test_unsupported_imports_equivalence_property_axioms_and_direct_grants_rejected(self):
        from rdflib import URIRef
        from rdflib.namespace import OWL, RDF
        ontology = Ontology({"A", "B"})
        for predicate, obj in ((OWL.imports, URIRef("https://example.com/external")),
                               (OWL.equivalentClass, URIRef(CLASS_NAMESPACE + "B")),
                               (OWL.someValuesFrom, URIRef(CLASS_NAMESPACE + "B"))):
            graph = ontology_to_rdf(ontology)
            graph.add((URIRef(CLASS_NAMESPACE + "A"), predicate, obj))
            self.assertFalse(validate_rdf_syntax(graph)["conforms"])
            with self.assertRaises(ValueError):
                ontology_from_rdf(graph)
        graph = ontology_to_rdf(ontology)
        graph.add((URIRef(POLICY_NAMESPACE + "external_approved_grant"), RDF.type, OWL.Class))
        with self.assertRaises(ValueError):
            ontology_from_rdf(graph)

    def test_malformed_cyclic_list_and_policy_antecedent_rejected(self):
        from rdflib import BNode, URIRef
        from rdflib.namespace import OWL, RDF, RDFS
        graph = ontology_to_rdf(Ontology({"A"}))
        intersection, items = BNode("i"), BNode("list")
        graph.add((intersection, RDF.type, OWL.Class))
        graph.add((intersection, OWL.intersectionOf, items))
        graph.add((intersection, RDFS.subClassOf, URIRef(POLICY_NAMESPACE + "can_read_body")))
        graph.add((items, RDF.first, URIRef(CLASS_NAMESPACE + "A")))
        graph.add((items, RDF.rest, items))
        with self.assertRaises(ValueError):
            ontology_from_rdf(graph)
        graph.set((items, RDF.rest, RDF.nil))
        graph.set((items, RDF.first, URIRef(POLICY_NAMESPACE + "can_write_body")))
        with self.assertRaises(ValueError):
            ontology_from_rdf(graph)


if __name__ == "__main__":
    unittest.main()
