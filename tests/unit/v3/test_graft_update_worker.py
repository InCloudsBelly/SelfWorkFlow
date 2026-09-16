import json
from pathlib import Path
import tempfile
import unittest


class FakeGraft:
    def __init__(
        self, *, missing=True, fail_build=False, unavailable=False,
        fail_status=False,
    ):
        self.missing = missing
        self.fail_build = fail_build
        self.unavailable = unavailable
        self.fail_status = fail_status
        self.builds = []

    def provider_preflight(self):
        if self.unavailable:
            from selfworkflow.v3.providers.graft import GraftAdapterError
            raise GraftAdapterError("graft-provider-unavailable")
        return {
            "providerId": "graft", "providerStatus": "verified",
            "version": "0.18.0", "queryCapabilities": [
                "build", "check",
                "ask", "callers", "grep", "map", "skeleton",
            ],
        }

    def status(self, project_root):
        if self.fail_status:
            from selfworkflow.v3.providers.graft import GraftAdapterError
            raise GraftAdapterError("graft-command-failed")
        return {
            "providerId": "graft",
            "initialized": not self.missing,
            "freshness": "missing" if self.missing else "fresh",
        }

    def build_structural(self, project_root):
        self.builds.append(project_root)
        if self.fail_build:
            from selfworkflow.v3.providers.graft import GraftAdapterError
            raise GraftAdapterError("graft-command-failed")
        self.missing = False
        return {"providerId": "graft", "operation": "build", "status": "succeeded"}


class GraftUpdateWorkerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        (self.root / ".git").mkdir()

    def test_first_code_preflight_initializes_missing_project_graph(self):
        from selfworkflow.v3.graft_lifecycle import GraftProjectLifecycle

        provider = FakeGraft()
        result = GraftProjectLifecycle(provider).preflight(str(self.root))

        self.assertEqual(result["status"], "initialized")
        self.assertEqual(result["providerStatus"], "verified")
        self.assertEqual(result["graphStatus"], "fresh")
        self.assertEqual(len(provider.builds), 1)
        self.assertIn("/graft/", (self.root / ".gitignore").read_text())

    def test_provider_unavailable_never_initializes_or_builds_project_graph(self):
        from selfworkflow.v3.graft_lifecycle import GraftProjectLifecycle

        provider = FakeGraft(unavailable=True)
        result = GraftProjectLifecycle(provider).preflight(str(self.root))

        self.assertEqual(result["status"], "unverified")
        self.assertEqual(result["providerStatus"], "unavailable")
        self.assertEqual(result["graphStatus"], "unknown")
        self.assertEqual(provider.builds, [])
        self.assertFalse((self.root / "graft").exists())
        self.assertFalse((self.root / ".gitignore").exists())

    def test_provider_unavailable_does_not_enqueue_or_create_project_cache(self):
        from selfworkflow.v3.graft_lifecycle import GraftProjectLifecycle

        result = GraftProjectLifecycle(FakeGraft(unavailable=True)).enqueue(
            str(self.root), ["src/a.cpp"],
        )

        self.assertEqual(result["status"], "unverified")
        self.assertFalse(result["pending"])
        self.assertEqual(result["providerStatus"], "unavailable")
        self.assertFalse((self.root / "graft").exists())
        self.assertFalse((self.root / ".gitignore").exists())

    def test_worker_keeps_existing_queue_when_provider_becomes_unavailable(self):
        from selfworkflow.v3.graft_lifecycle import GraftProjectLifecycle

        provider = FakeGraft(missing=False)
        lifecycle = GraftProjectLifecycle(provider)
        lifecycle.enqueue(str(self.root), ["src/a.cpp"])
        provider.unavailable = True

        result = lifecycle.run_once(
            str(self.root), conversation_id="thread-provider-failure",
        )

        self.assertEqual(result["status"], "unverified")
        self.assertTrue(result["pending"])
        self.assertEqual(provider.builds, [])
        queue = json.loads(
            (self.root / "graft/.cache/selfworkflow/queue.json").read_text()
        )
        self.assertEqual(queue["changedPaths"], ["src/a.cpp"])

    def test_query_fails_closed_when_provider_preflight_is_unavailable(self):
        from selfworkflow.v3.graft_lifecycle import (
            GraftProjectError, GraftProjectLifecycle,
        )

        with self.assertRaisesRegex(
            GraftProjectError, "graft-provider-unavailable",
        ):
            GraftProjectLifecycle(FakeGraft(unavailable=True)).query(
                str(self.root), "helper", query_kind="ask",
            )

    def test_graph_check_failure_preserves_verified_provider_state(self):
        from selfworkflow.v3.graft_lifecycle import GraftProjectLifecycle

        result = GraftProjectLifecycle(
            FakeGraft(missing=False, fail_status=True),
        ).preflight(str(self.root))

        self.assertEqual(result["status"], "unverified")
        self.assertEqual(result["providerStatus"], "verified")
        self.assertEqual(result["graphStatus"], "unknown")
        self.assertEqual(result["reason"], "graft-command-failed")

    def test_write_events_are_coalesced_into_one_structural_build(self):
        from selfworkflow.v3.graft_lifecycle import GraftProjectLifecycle

        provider = FakeGraft(missing=False)
        lifecycle = GraftProjectLifecycle(provider)
        first = lifecycle.enqueue(str(self.root), ["src/a.cpp"])
        second = lifecycle.enqueue(str(self.root), ["src/b.cpp", "src/a.cpp"])

        self.assertEqual(first["status"], "queued")
        self.assertEqual(second["status"], "coalesced")
        result = lifecycle.run_once(
            str(self.root), conversation_id="thread-coalesced",
        )
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(len(provider.builds), 1)
        state = json.loads(
            (self.root / "graft/.cache/selfworkflow/state.json").read_text()
        )
        self.assertEqual(state["lastChangedPaths"], ["src/a.cpp", "src/b.cpp"])

    def test_build_failure_retains_retryable_pending_event_and_old_graph(self):
        from selfworkflow.v3.graft_lifecycle import GraftProjectLifecycle

        provider = FakeGraft(missing=False, fail_build=True)
        lifecycle = GraftProjectLifecycle(provider)
        lifecycle.enqueue(str(self.root), ["src/a.cpp"])

        result = lifecycle.run_once(
            str(self.root), conversation_id="thread-build-failure",
        )

        self.assertEqual(result["status"], "partial")
        self.assertTrue(result["retryable"])
        queue = json.loads(
            (self.root / "graft/.cache/selfworkflow/queue.json").read_text()
        )
        self.assertEqual(queue["changedPaths"], ["src/a.cpp"])

    def test_query_path_never_creates_worker_queue(self):
        from selfworkflow.v3.graft_lifecycle import GraftProjectLifecycle

        provider = FakeGraft(missing=False)
        lifecycle = GraftProjectLifecycle(provider)

        result = lifecycle.query_status(str(self.root))

        self.assertEqual(result["freshness"], "fresh")
        self.assertFalse((self.root / "graft").exists())

    def test_topic_status_and_query_use_only_the_explicit_topic_context(self):
        from selfworkflow.v3.graft_lifecycle import GraftProjectLifecycle

        topic = self.root / ".selfworkflow" / "graft-deep" / "kgpr" / "graft"
        topic.mkdir(parents=True)
        (self.root / "graft").write_text("root cache is not part of this query", encoding="utf-8")

        class TopicGraft(FakeGraft):
            def __init__(self):
                super().__init__(missing=False)
                self.status_contexts = []
                self.query_contexts = []

            def status(self, project_root, *, context_dir=None):
                self.status_contexts.append(context_dir)
                return super().status(project_root)

            def query(self, project_root, query, *, query_kind, context_dir=None):
                self.query_contexts.append(context_dir)
                return {"providerId": "graft", "data": {"hits": []}}

        provider = TopicGraft()
        lifecycle = GraftProjectLifecycle(provider)

        status = lifecycle.query_status(str(self.root), context_dir=str(topic))
        result = lifecycle.query(
            str(self.root), "Widget", query_kind="ask", context_dir=str(topic),
        )

        self.assertEqual(status["freshness"], "fresh")
        self.assertEqual(result["data"], {"hits": []})
        self.assertEqual(provider.status_contexts, [str(topic.resolve())])
        self.assertEqual(provider.query_contexts, [str(topic.resolve())])
        self.assertEqual(
            (self.root / "graft").read_text(encoding="utf-8"),
            "root cache is not part of this query",
        )

    def test_topic_context_must_be_existing_and_inside_selfworkflow_topic_root(self):
        from selfworkflow.v3.graft_lifecycle import (
            GraftProjectError, GraftProjectLifecycle,
        )

        lifecycle = GraftProjectLifecycle(FakeGraft(missing=False))
        with self.assertRaisesRegex(GraftProjectError, "graft-topic-context-invalid"):
            lifecycle.query_status(
                str(self.root),
                context_dir=str(self.root / "graft"),
            )

    def test_conversation_topic_binding_round_trips_without_persisting_raw_id(self):
        from selfworkflow.v3.graft_lifecycle import (
            bind_conversation_topic, resolve_conversation_topic,
        )

        topic = self.root / ".selfworkflow" / "graft-deep" / "kgpr" / "graft"
        topic.mkdir(parents=True)
        conversation_id = "thread-019-example"

        created = bind_conversation_topic(self.root, conversation_id, "kgpr")

        self.assertEqual(created["status"], "created")
        self.assertEqual(created["topicId"], "kgpr")
        self.assertEqual(
            resolve_conversation_topic(self.root, conversation_id)["topicId"],
            "kgpr",
        )
        binding_files = list(
            (self.root / ".selfworkflow" / "graft-deep" / ".conversation-bindings")
            .glob("*.json")
        )
        self.assertEqual(len(binding_files), 1)
        self.assertNotIn(conversation_id, binding_files[0].read_text(encoding="utf-8"))

    def test_conversation_cannot_switch_topics_and_missing_binding_fails_closed(self):
        from selfworkflow.v3.graft_lifecycle import (
            GraftProjectError, bind_conversation_topic, resolve_conversation_topic,
        )

        conversation_id = "thread-bound"
        with self.assertRaisesRegex(GraftProjectError, "graft-conversation-topic-mismatch"):
            bind_conversation_topic(self.root, conversation_id, "topic-a")
            bind_conversation_topic(self.root, conversation_id, "topic-b")
        self.assertIsNone(resolve_conversation_topic(self.root, "thread-other"))

    def test_new_conversation_lists_existing_topics_and_selection_binds_it(self):
        from selfworkflow.v3.graft_lifecycle import (
            choose_conversation_topic, list_graft_topics,
            resolve_conversation_topic,
        )
        from selfworkflow.v3.hashing import content_hash, hash_file_content, project_root_hash

        source = self.root / "Source" / "main.cpp"
        source.parent.mkdir()
        source.write_text("int main() {}", encoding="utf-8")
        size, digest = hash_file_content(source)
        for topic_id in ("kgpr", "lighting"):
            topic_root = self.root / ".selfworkflow" / "graft-deep" / topic_id
            (topic_root / "graft").mkdir(parents=True)
            scope = [{"path": "Source/main.cpp", "size": size, "sha256": digest}]
            (topic_root / "selfworkflow-topic.json").write_text(
                json.dumps({
                    "kind": "selfworkflow-graft-topic", "version": 1,
                    "topicId": topic_id, "projectRootHash": project_root_hash(self.root),
                    "scopeFiles": scope, "scopeHash": content_hash(scope),
                    "freshness": "fresh",
                }),
                encoding="utf-8",
            )

        result = list_graft_topics(self.root)

        self.assertEqual([item["topicId"] for item in result["topics"]], ["kgpr", "lighting"])
        self.assertTrue(all(item["selectable"] for item in result["topics"]))
        selected = choose_conversation_topic(self.root, "thread-new", "kgpr")
        self.assertEqual(selected["status"], "created")
        self.assertEqual(resolve_conversation_topic(self.root, "thread-new")["topicId"], "kgpr")

    def test_conversation_can_be_marked_no_topic_and_never_falls_back_to_root_graft(self):
        from selfworkflow.v3.graft_lifecycle import (
            GraftProjectError, GraftProjectLifecycle,
            disable_conversation_graft, resolve_conversation_choice,
        )

        choice = disable_conversation_graft(self.root, "thread-no-graft")
        self.assertEqual(choice["status"], "disabled")
        self.assertEqual(
            resolve_conversation_choice(self.root, "thread-no-graft")["decision"],
            "disabled",
        )
        status = GraftProjectLifecycle(FakeGraft(missing=False)).query_status(
            str(self.root), conversation_id="thread-no-graft",
        )
        self.assertEqual(status["status"], "disabled")
        self.assertEqual(status["conversationChoice"]["choice"], "no-deep-topic")
        with self.assertRaisesRegex(GraftProjectError, "graft-disabled-for-conversation"):
            GraftProjectLifecycle(FakeGraft(missing=False)).query(
                str(self.root), "ignored", query_kind="ask",
                conversation_id="thread-no-graft",
            )

    def test_disabled_conversation_cannot_be_rebound_to_topic(self):
        from selfworkflow.v3.graft_lifecycle import (
            GraftProjectError, choose_conversation_topic, disable_conversation_graft,
        )

        topic = self.root / ".selfworkflow" / "graft-deep" / "kgpr" / "graft"
        topic.mkdir(parents=True)
        disable_conversation_graft(self.root, "thread-locked")
        with self.assertRaisesRegex(GraftProjectError, "graft-conversation-choice-locked"):
            choose_conversation_topic(self.root, "thread-locked", "kgpr")

    def test_status_and_query_can_resolve_topic_from_conversation_binding(self):
        from selfworkflow.v3.graft_lifecycle import (
            GraftProjectLifecycle, bind_conversation_topic,
        )

        topic = self.root / ".selfworkflow" / "graft-deep" / "kgpr" / "graft"
        topic.mkdir(parents=True)
        bind_conversation_topic(self.root, "thread-bound", "kgpr")

        class TopicGraft(FakeGraft):
            def __init__(self):
                super().__init__(missing=False)
                self.status_contexts = []
                self.query_contexts = []

            def status(self, project_root, *, context_dir=None):
                self.status_contexts.append(context_dir)
                return super().status(project_root)

            def query(self, project_root, query, *, query_kind, context_dir=None):
                self.query_contexts.append(context_dir)
                return {"providerId": "graft", "data": {"hits": []}}

        provider = TopicGraft()
        lifecycle = GraftProjectLifecycle(provider)
        status = lifecycle.query_status(
            str(self.root), conversation_id="thread-bound",
        )
        result = lifecycle.query(
            str(self.root), "Widget", query_kind="ask",
            conversation_id="thread-bound",
        )

        expected = str(topic.resolve())
        self.assertEqual(provider.status_contexts, [expected])
        self.assertEqual(provider.query_contexts, [expected])
        self.assertEqual(status["conversationBinding"]["topicId"], "kgpr")
        self.assertEqual(result["conversationBinding"]["conversationId"], "thread-bound")

    def test_topic_status_exposes_stale_scope_files_for_automatic_deep_refresh(self):
        from selfworkflow.v3.graft_lifecycle import GraftProjectLifecycle, bind_conversation_topic
        from selfworkflow.v3.hashing import content_hash, project_root_hash

        topic = self.root / ".selfworkflow" / "graft-deep" / "kgpr" / "graft"
        topic.mkdir(parents=True)
        source = self.root / "Source" / "main.cpp"
        source.parent.mkdir()
        source.write_text("int changed() {}", encoding="utf-8")
        bind_conversation_topic(self.root, "thread-stale", "kgpr")
        scope = [{
            "path": "Source/main.cpp", "size": 1,
            "sha256": "sha256:" + "0" * 64,
        }]
        (topic.parent / "selfworkflow-topic.json").write_text(
            json.dumps({
                "kind": "selfworkflow-graft-topic", "version": 1,
                "topicId": "kgpr", "projectRootHash": project_root_hash(self.root),
                "scopeFiles": scope, "scopeHash": content_hash(scope),
                "model": "gpt-5.6-luna", "reasoningEffort": "xhigh",
                "graftCommandHash": content_hash(["node", "graft"]),
                "freshness": "fresh",
            }),
            encoding="utf-8",
        )

        class TopicGraft(FakeGraft):
            def status(self, project_root, *, context_dir=None):
                return super().status(project_root)

        result = GraftProjectLifecycle(TopicGraft()).query_status(
            str(self.root), conversation_id="thread-stale",
        )

        self.assertEqual(result["freshness"], "stale")
        self.assertEqual(result["topicFreshness"], "stale")
        self.assertEqual(result["topicStaleFiles"], ["Source/main.cpp"])

    def test_topic_refresh_is_prioritized_and_defers_global_map(self):
        from selfworkflow.v3.graft_lifecycle import (
            GraftProjectLifecycle, bind_conversation_topic,
        )
        from selfworkflow.v3.hashing import content_hash, hash_file_content, project_root_hash

        topic = self.root / ".selfworkflow" / "graft-deep" / "kgpr" / "graft"
        topic.mkdir(parents=True)
        source = self.root / "Source" / "main.cpp"
        source.parent.mkdir()
        source.write_text("int changed() {}", encoding="utf-8")
        bind_conversation_topic(self.root, "thread-write", "kgpr")
        scope = [{"path": "Source/main.cpp", "size": 1, "sha256": "sha256:" + "0" * 64}]
        (topic.parent / "selfworkflow-topic.json").write_text(
            json.dumps({
                "kind": "selfworkflow-graft-topic", "version": 1,
                "topicId": "kgpr", "projectRootHash": project_root_hash(self.root),
                "scopeFiles": scope, "scopeHash": content_hash(scope),
                "freshness": "fresh",
            }),
            encoding="utf-8",
        )

        result = GraftProjectLifecycle(FakeGraft(missing=False))
        result.enqueue(str(self.root), ["Source/main.cpp"])
        outcome = result.run_once(str(self.root), conversation_id="thread-write")

        self.assertEqual(outcome["status"], "partial")
        self.assertEqual(outcome["globalMap"]["status"], "deferred")
        self.assertEqual(outcome["globalMap"]["reason"], "topic-refresh-priority")
        self.assertEqual(outcome["globalMapUpdated"], False)
        self.assertEqual(outcome["topicRefresh"]["status"], "refresh-required")
        self.assertEqual(outcome["topicRefresh"]["topicId"], "kgpr")
        self.assertEqual(outcome["topicRefresh"]["staleFiles"], ["Source/main.cpp"])
        self.assertEqual(outcome["conversationId"], "thread-write")
        self.assertEqual(outcome["topicRefresh"]["conversationId"], "thread-write")
        self.assertEqual(outcome["globalMap"]["deep"], False)
        self.assertEqual(outcome["nextAction"], "run-graft-deep")
        self.assertEqual(result._provider.builds, [])

    def test_global_map_failure_does_not_block_bound_topic_refresh(self):
        from selfworkflow.v3.graft_lifecycle import (
            GraftProjectLifecycle, bind_conversation_topic,
        )
        from selfworkflow.v3.hashing import (
            content_hash, hash_file_content, project_root_hash,
        )

        topic = self.root / ".selfworkflow" / "graft-deep" / "kgpr" / "graft"
        topic.mkdir(parents=True)
        source = self.root / "Source" / "main.cpp"
        source.parent.mkdir()
        source.write_text("int changed() {}", encoding="utf-8")
        bind_conversation_topic(self.root, "thread-global-failure", "kgpr")
        size, digest = hash_file_content(source)
        scope = [{
            "path": "Source/main.cpp", "size": size, "sha256": digest,
        }]
        (topic.parent / "selfworkflow-topic.json").write_text(
            json.dumps({
                "kind": "selfworkflow-graft-topic", "version": 1,
                "topicId": "kgpr", "projectRootHash": project_root_hash(self.root),
                "scopeFiles": scope, "scopeHash": content_hash(scope),
                "freshness": "fresh",
            }),
            encoding="utf-8",
        )

        lifecycle = GraftProjectLifecycle(
            FakeGraft(missing=False, fail_build=True),
        )
        lifecycle.enqueue(str(self.root), ["Source/main.cpp"])

        outcome = lifecycle.run_once(
            str(self.root), conversation_id="thread-global-failure",
        )

        self.assertEqual(outcome["status"], "partial")
        self.assertEqual(outcome["globalMap"]["status"], "failed")
        self.assertFalse(outcome["globalMapUpdated"])
        self.assertEqual(outcome["topicRefresh"]["status"], "fresh")
        self.assertEqual(outcome["topicRefresh"]["action"], "none")
        self.assertEqual(outcome["nextAction"], "retry-global-map")
        self.assertTrue(outcome["pending"])

    def test_global_map_retry_consumes_retained_event_after_provider_recovers(self):
        from selfworkflow.v3.graft_lifecycle import (
            GraftProjectLifecycle, bind_conversation_topic,
        )
        from selfworkflow.v3.hashing import (
            content_hash, hash_file_content, project_root_hash,
        )

        topic = self.root / ".selfworkflow" / "graft-deep" / "kgpr" / "graft"
        topic.mkdir(parents=True)
        source = self.root / "Source" / "main.cpp"
        source.parent.mkdir()
        source.write_text("int changed() {}", encoding="utf-8")
        bind_conversation_topic(self.root, "thread-global-retry", "kgpr")
        size, digest = hash_file_content(source)
        scope = [{"path": "Source/main.cpp", "size": size, "sha256": digest}]
        (topic.parent / "selfworkflow-topic.json").write_text(
            json.dumps({
                "kind": "selfworkflow-graft-topic", "version": 1,
                "topicId": "kgpr", "projectRootHash": project_root_hash(self.root),
                "scopeFiles": scope, "scopeHash": content_hash(scope),
                "freshness": "fresh",
            }),
            encoding="utf-8",
        )

        provider = FakeGraft(missing=False, fail_build=True)
        lifecycle = GraftProjectLifecycle(provider)
        lifecycle.enqueue(str(self.root), ["Source/main.cpp"])

        failed = lifecycle.run_once(
            str(self.root), conversation_id="thread-global-retry",
        )
        self.assertEqual(failed["nextAction"], "retry-global-map")
        self.assertTrue(failed["pending"])

        provider.fail_build = False
        recovered = lifecycle.run_once(
            str(self.root), conversation_id="thread-global-retry",
        )
        self.assertEqual(recovered["status"], "succeeded")
        self.assertTrue(recovered["globalMapUpdated"])
        self.assertEqual(recovered["globalMap"]["status"], "succeeded")
        self.assertFalse(recovered["pending"])
        self.assertEqual(recovered["nextAction"], "none")
        self.assertEqual(len(provider.builds), 2)

    def test_stale_topic_is_prioritized_before_slow_global_map_build(self):
        from selfworkflow.v3.graft_lifecycle import (
            GraftProjectLifecycle, bind_conversation_topic,
        )
        from selfworkflow.v3.hashing import content_hash, project_root_hash

        topic = self.root / ".selfworkflow" / "graft-deep" / "kgpr" / "graft"
        topic.mkdir(parents=True)
        source = self.root / "Source" / "main.cpp"
        source.parent.mkdir()
        source.write_text("int changed() {}", encoding="utf-8")
        bind_conversation_topic(self.root, "thread-topic-first", "kgpr")
        scope = [{
            "path": "Source/main.cpp", "size": 1,
            "sha256": "sha256:" + "0" * 64,
        }]
        (topic.parent / "selfworkflow-topic.json").write_text(
            json.dumps({
                "kind": "selfworkflow-graft-topic", "version": 1,
                "topicId": "kgpr", "projectRootHash": project_root_hash(self.root),
                "scopeFiles": scope, "scopeHash": content_hash(scope),
                "freshness": "fresh",
            }),
            encoding="utf-8",
        )

        provider = FakeGraft(missing=False, fail_build=True)
        lifecycle = GraftProjectLifecycle(provider)
        lifecycle.enqueue(str(self.root), ["Source/main.cpp"])

        outcome = lifecycle.run_once(
            str(self.root), conversation_id="thread-topic-first",
        )

        self.assertEqual(provider.builds, [])
        self.assertEqual(outcome["status"], "partial")
        self.assertEqual(outcome["globalMap"]["status"], "deferred")
        self.assertEqual(outcome["topicRefresh"]["action"], "run-graft-deep")
        self.assertEqual(outcome["nextAction"], "run-graft-deep")
        self.assertTrue(outcome["pending"])
        queue = json.loads(
            (self.root / "graft/.cache/selfworkflow/queue.json").read_text()
        )
        self.assertEqual(queue["changedPaths"], ["Source/main.cpp"])

    def test_worker_requires_conversation_identity_instead_of_global_only_success(self):
        from selfworkflow.v3.graft_lifecycle import GraftProjectError, GraftProjectLifecycle

        lifecycle = GraftProjectLifecycle(FakeGraft(missing=False))
        lifecycle.enqueue(str(self.root), ["src/a.cpp"])

        with self.assertRaisesRegex(
            GraftProjectError, "graft-conversation-id-invalid",
        ):
            lifecycle.run_once(str(self.root), conversation_id=None)

        self.assertEqual(lifecycle._provider.builds, [])

    def test_outside_or_graph_paths_are_rejected(self):
        from selfworkflow.v3.graft_lifecycle import GraftProjectError, GraftProjectLifecycle

        provider = FakeGraft(missing=False)
        lifecycle = GraftProjectLifecycle(provider)
        with self.assertRaisesRegex(GraftProjectError, "graft-event-path-invalid"):
            lifecycle.enqueue(str(self.root), ["graft/INDEX.md"])


if __name__ == "__main__":
    unittest.main()
