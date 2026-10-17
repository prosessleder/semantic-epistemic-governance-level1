import itertools
import unittest

from ontology_boundary.store_simulator import (
    AdapterContract, ArtifactStore, Eligibility, FlowGrant, Principal, ToolACL,
    field_complete_reachability,
)


class StoreAdapterTests(unittest.TestCase):
    def setUp(self):
        self.source = Principal("writer", "task-A")
        self.foreign = Principal("reader", "task-B")
        self.same_task = Principal("peer", "task-A")
        self.acl = ToolACL()
        self.writer = Eligibility(write_fields={"body", "metadata"})
        self.reader = Eligibility(read_fields={"body", "metadata"})
        self.contract = AdapterContract({"metadata"})

    def simulate(self, field, *, source_eligibility=None, destination=None,
                 contract=None, grants=(), enforced=False, source_acl=None, destination_acl=None):
        destination = destination or self.foreign
        source_eligibility = source_eligibility or self.writer
        source_acl, destination_acl = source_acl or self.acl, destination_acl or self.acl
        contract = contract or self.contract
        store = ArtifactStore(contract, enforce_task_boundary=enforced)
        write = store.write_field(self.source, source_acl, source_eligibility, field, "local-test-marker")
        observed = store.observe_field(self.source, destination, destination_acl, self.reader, field, grants)
        graph = field_complete_reachability(self.source, destination, field,
            source_acl=source_acl, destination_acl=destination_acl,
            source_eligibility=source_eligibility, destination_eligibility=self.reader,
            contract=contract, grants=grants, enforce_task_boundary=enforced)
        self.assertEqual(graph.route_exists, observed.event.admitted)
        self.assertEqual(graph.unauthorized_route, observed.unauthorized_delivery)
        return write, observed, graph

    def test_body_private_metadata_foreign_visible_despite_same_tool_acl(self):
        _, body, body_graph = self.simulate("body")
        _, metadata, metadata_graph = self.simulate("metadata")
        self.assertIsNone(body.value)
        self.assertEqual(body.event.reason, "adapter_private")
        self.assertEqual(metadata.value, "local-test-marker")
        self.assertTrue(metadata.unauthorized_delivery)
        self.assertFalse(body_graph.route_exists)
        self.assertEqual(metadata_graph.witness_path, ("source", "artifact:metadata", "destination"))

    def test_eligibility_revision_changes_route_on_same_operational_contract(self):
        old = Eligibility(write_fields={"body"})
        old_write, before, _ = self.simulate("metadata", source_eligibility=old)
        new_write, after, _ = self.simulate("metadata", source_eligibility=self.writer)
        self.assertFalse(old_write.admitted)
        self.assertEqual(before.event.reason, "no_record_field")
        self.assertTrue(new_write.admitted)
        self.assertTrue(after.unauthorized_delivery)
        self.assertEqual(self.acl.sha256, ToolACL().sha256)
        self.assertEqual(self.contract.operational_sha256, AdapterContract({"metadata"}).operational_sha256)

    def test_adapter_revision_changes_visibility_without_eligibility_or_acl_change(self):
        private = AdapterContract(set())
        _, before, _ = self.simulate("metadata", contract=private)
        _, after, _ = self.simulate("metadata", contract=self.contract)
        self.assertIsNone(before.value)
        self.assertEqual(after.value, "local-test-marker")
        self.assertNotEqual(private.operational_sha256, self.contract.operational_sha256)

    def test_annotation_only_relabeling_does_not_create_an_operational_route(self):
        before_contract = AdapterContract({"metadata"}, (("role", "artifact-store"),))
        after_contract = AdapterContract({"metadata"}, (("role", "coordination-channel"),))
        _, before, _ = self.simulate("metadata", contract=before_contract)
        _, after, _ = self.simulate("metadata", contract=after_contract)
        self.assertEqual(before, after)
        self.assertTrue(before.unauthorized_delivery)
        self.assertEqual(before_contract.operational_sha256, after_contract.operational_sha256)

    def test_complete_mediation_blocks_foreign_flow_and_exact_grant_restores_it(self):
        _, blocked, graph = self.simulate("metadata", enforced=True)
        self.assertEqual(blocked.event.reason, "task_boundary")
        self.assertFalse(graph.route_exists)
        grant = FlowGrant(self.source, self.foreign, {"metadata"})
        _, allowed, _ = self.simulate("metadata", grants=(grant,), enforced=True)
        self.assertEqual(allowed.value, "local-test-marker")
        self.assertFalse(allowed.unauthorized_delivery)
        _, same, _ = self.simulate("body", destination=self.same_task, enforced=True)
        self.assertEqual(same.value, "local-test-marker")

    def test_grant_is_exact_in_actor_task_field_and_approval(self):
        grants = (
            FlowGrant(Principal("other", "task-A"), self.foreign, {"metadata"}),
            FlowGrant(self.source, Principal("other", "task-B"), {"metadata"}),
            FlowGrant(Principal("writer", "stale-task"), self.foreign, {"metadata"}),
            FlowGrant(self.source, Principal("reader", "other-task"), {"metadata"}),
            FlowGrant(self.source, self.foreign, {"body"}),
            FlowGrant(self.source, self.foreign, {"metadata"}, False),
        )
        for grant in grants:
            with self.subTest(grant=grant):
                _, observation, _ = self.simulate("metadata", grants=(grant,), enforced=True)
                self.assertEqual(observation.event.reason, "task_boundary")

    def test_grant_neither_creates_visibility_nor_overrides_tool_or_eligibility(self):
        grant = FlowGrant(self.source, self.foreign, {"body", "metadata"})
        _, body, _ = self.simulate("body", grants=(grant,), enforced=True)
        self.assertEqual(body.event.reason, "adapter_private")
        _, denied_write, _ = self.simulate("metadata", source_acl=ToolACL(write_artifact=False), grants=(grant,))
        self.assertIsNone(denied_write.value)
        _, denied_read, _ = self.simulate("metadata", destination_acl=ToolACL(list_artifacts=False), grants=(grant,))
        self.assertEqual(denied_read.event.reason, "tool_acl")

    def test_bfs_matches_operational_adapter_across_256_distinct_contexts(self):
        contexts = itertools.product((False, True), repeat=8)
        count = 0
        for write, read, write_acl, read_acl, visible, same_task, approved, enforced in contexts:
            owner = Principal("writer", "A")
            destination = Principal("reader", "A" if same_task else "B")
            src = Eligibility(write_fields={"metadata"} if write else set())
            dst = Eligibility(read_fields={"metadata"} if read else set())
            src_acl, dst_acl = ToolACL(write_artifact=write_acl), ToolACL(list_artifacts=read_acl)
            contract = AdapterContract({"metadata"} if visible else set())
            grant = FlowGrant(owner, destination, {"metadata"}, approved)
            store = ArtifactStore(contract, enforce_task_boundary=enforced)
            store.write_field(owner, src_acl, src, "metadata", "m")
            observation = store.observe_field(owner, destination, dst_acl, dst, "metadata", (grant,))
            graph = field_complete_reachability(owner, destination, "metadata",
                source_acl=src_acl, destination_acl=dst_acl, source_eligibility=src,
                destination_eligibility=dst, contract=contract, grants=(grant,), enforce_task_boundary=enforced)
            self.assertEqual(graph.route_exists, observation.event.admitted)
            self.assertEqual(graph.unauthorized_route, observation.unauthorized_delivery)
            count += 1
        self.assertEqual(count, 256)

    def test_unsupported_fields_and_untrusted_grant_shapes_are_rejected(self):
        with self.assertRaises(ValueError):
            AdapterContract({"network"})
        with self.assertRaises(ValueError):
            Eligibility(write_fields="metadata")
        with self.assertRaises(ValueError):
            ToolACL(list_artifacts=1)
        store = ArtifactStore(self.contract)
        with self.assertRaises(ValueError):
            store.write_field(self.source, self.acl, self.writer, "metadata", {"text": "m"})
        with self.assertRaises(ValueError):
            store.observe_field(self.source, self.foreign, self.acl, self.reader, "metadata", ({"approved": True},))


if __name__ == "__main__":
    unittest.main()
