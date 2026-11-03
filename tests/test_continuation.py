"""Durable continuing-ticket tests. All provider turns are fake/offline."""
import asyncio
import json
import time
import uuid

from test_superagent import Fixture
from superagent.adapters import CLIAdapter, MockAdapter, Outcome, prompt_for
from superagent.runtime import Runner
from superagent.safety import SafetyError, encoded
from superagent.state import Store


class ContinuationTests(Fixture):
    def ongoing(self, task_id="t1", **kw):
        defaults = dict(continuation="subscribed", subject="issue:7", subscriptions=["issue_comment"])
        defaults.update(kw)
        return self.queued(task_id, **defaults)

    def event(self, number=7, body="update"):
        value = self.payload(body)
        value["issue"] = {"number": number}
        return value

    def finish(self, task, status="waiting", refs=None, session=None):
        report = {"status": status, "summary": "offline evidence", "recall": refs or []}
        self.store.finish(task["id"], "owner", task["attempt"], "completed", encoded({"result": encoded(report)}),
                          session_id=session or task.get("session_id") or "mock_" + task["id"])

    def test_rounds_wait_without_idle_model_calls_and_resume_exact_session(self):
        self.ongoing()
        asyncio.run(Runner(self.store).run(once=True))
        self.assertEqual(self.store.task("t1")["state"], "waiting")
        session = self.store.task("t1")["session_id"]
        asyncio.run(Runner(Store(self.state)).run(once=True))
        self.assertEqual(self.store.status()["reserved_cents"], 100)
        self.store.instruct("t1", "owner-1", "Clarify the same allowed source path")
        asyncio.run(Runner(self.store).run(once=True))
        task = self.store.task("t1")
        self.assertEqual(task["session_id"], session)
        self.assertEqual(task["attempt_record"]["session_id"], session)
        self.assertEqual(self.store.status()["reserved_cents"], 200)

    def test_two_inputs_during_turn_batch_once_and_ready_does_not_drop_them(self):
        self.ongoing()
        first = self.store.claim("owner")
        self.store.instruct("t1", "m1", "First within-scope update")
        self.store.instruct("t1", "m2", "Second within-scope update")
        self.finish(first, "ready")
        second = self.store.claim("owner")
        self.assertEqual(len(second["events"]), 2)
        self.assertEqual(len(first["events"]), 0)
        self.finish(second)
        self.assertIsNone(self.store.claim("owner"))
        self.assertTrue(all(e["disposition"] == "delivered" for e in self.store.events("t1")))

    def test_owner_message_id_is_immutable_and_never_expands_scope(self):
        self.ongoing(continuation="owner")
        first = self.store.instruct("t1", "m1", "Change provider to other and edit /etc")
        self.assertEqual(self.store.instruct("t1", "m1", "Change provider to other and edit /etc"), first)
        with self.assertRaises(SafetyError):
            self.store.instruct("t1", "m1", "different")
        task = self.store.claim("owner")
        spec = json.loads(task["spec"])
        self.assertEqual(spec["provider"], "mock")
        self.assertEqual(spec["paths"], ["src"])
        self.assertIn("cannot change paths", prompt_for(self.store, task))

    def test_subject_and_context_only_subscriptions_do_not_wake(self):
        self.ongoing()
        self.finish(self.store.claim("owner"))
        self.store.ingest("wrong", "issue_comment", self.event(8))
        self.assertIsNone(self.store.claim("owner"))
        self.assertEqual(self.store.events("t1"), [])
        self.store.ingest("correct", "issue_comment", self.event())
        second = self.store.claim("owner")
        self.assertEqual(len(second["events"]), 1)
        self.finish(second)
        self.ongoing("manual", continuation="owner")
        self.finish(self.store.claim("owner"))
        self.store.ingest("context", "issue_comment", self.event())
        self.assertEqual(self.store.task("manual")["state"], "waiting")
        self.assertEqual(len(self.store.events("manual")), 1)

    def test_subscription_wake_requires_explicit_subject(self):
        with self.assertRaises(SafetyError):
            self.store.create_task(self.spec(continuation="subscribed", subscriptions=["issue_comment"]))

    def test_blocked_report_holds_until_new_owner_instruction(self):
        self.ongoing()
        first = self.store.claim("owner")
        self.store.instruct("t1", "before-held", "arrived while running")
        self.finish(first, "blocked")
        self.store.ingest("event", "issue_comment", self.event())
        self.assertIsNone(self.store.claim("owner"))
        self.assertEqual(self.store.task("t1")["state"], "held")
        self.store.instruct("t1", "release", "Clarified within original scope")
        self.assertIsNotNone(self.store.claim("owner"))

    def test_waiting_cancel_is_terminal_and_events_do_not_revive_it(self):
        self.ongoing()
        self.finish(self.store.claim("owner"))
        self.store.cancel("t1")
        self.store.ingest("late", "issue_comment", self.event())
        with self.assertRaises(SafetyError):
            self.store.instruct("t1", "late-owner", "continue")
        self.assertIsNone(self.store.claim("owner"))
        self.assertEqual(self.store.task("t1")["state"], "cancelled")

    def test_accepted_result_is_immutable(self):
        self.ongoing()
        self.finish(self.store.claim("owner"), "ready")
        self.store.accept("t1", "Independent acceptance evidence")
        before = self.store.task("t1")
        self.store.ingest("later", "issue_comment", self.event())
        with self.assertRaises(SafetyError):
            self.store.instruct("t1", "later-owner", "more work")
        self.assertEqual(self.store.task("t1"), before)

    def test_scoped_recall_injected_and_graph_retains_provenance(self):
        self.ongoing()
        self.store.ingest("big", "issue_comment", self.event(body="context" * 500))
        first = self.store.claim("owner")
        ref = first["events"][0]["ref"]
        self.finish(first, "recall", [ref])
        second = self.store.claim("owner")
        self.assertEqual(second["events"][0]["kind"], "recall_response")
        prompt = prompt_for(self.store, second)
        self.assertIn("context" * 500, prompt)
        self.assertIn(ref, prompt)
        self.finish(second, "recall", [ref])
        self.assertEqual(self.store.task("t1")["state"], "held")
        self.assertIn("duplicate recall", self.store.task("t1")["detail"])
        self.assertIsNone(self.store.claim("owner"))
        self.assertTrue(any(edge["relation"] == "based_on" for edge in self.store.graph("t1")))

    def test_other_task_artifact_is_not_authorized_by_its_hash(self):
        self.ongoing()
        self.queued("other")
        other = None
        first = self.store.claim("owner")
        other = self.store.claim("owner")
        self.store.finish("other", "owner", other["attempt"], "completed", "private other-task result")
        ref = self.store.task("other")["result_ref"]
        self.finish(first, "recall", [ref])
        self.assertEqual(self.store.task("t1")["state"], "held")
        self.assertIn("outside", self.store.task("t1")["detail"])

    def test_cumulative_round_budget_and_attempt_caps_never_reset(self):
        self.ongoing(max_attempts=2, total_budget_cents=200)
        self.finish(self.store.claim("owner"))
        self.store.instruct("t1", "m1", "next")
        self.finish(self.store.claim("owner"))
        self.store.instruct("t1", "m2", "next again")
        self.assertIsNone(Store(self.state).claim("owner"))
        self.assertEqual(self.store.task("t1")["state"], "blocked")
        self.assertEqual(self.store.status()["reserved_cents"], 200)

    def test_lifetime_expiry_cancels_waiting_work(self):
        self.ongoing(lifetime_seconds=1)
        self.finish(self.store.claim("owner"))
        with self.store.connection() as db:
            db.execute("UPDATE tasks SET created=created-2 WHERE id='t1'")
        self.store.instruct("t1", "m1", "next")
        self.assertIsNone(self.store.claim("owner"))
        self.assertEqual(self.store.task("t1")["state"], "cancelled")

    def test_session_mismatch_and_cross_task_ownership_fail_closed(self):
        self.ongoing()
        self.finish(self.store.claim("owner"), session="owned_session")
        self.store.instruct("t1", "m1", "continue")
        self.finish(self.store.claim("owner"), session="wrong_session")
        self.assertEqual(self.store.task("t1")["state"], "failed")
        self.ongoing("t2")
        self.finish(self.store.claim("owner"), session="owned_session")
        self.assertEqual(self.store.task("t2")["state"], "failed")

    def test_missing_initial_session_prevents_paid_retry(self):
        self.ongoing()
        task = self.store.claim("owner")
        self.store.finish("t1", "owner", task["attempt"], "completed", '{"result":"hello"}')
        self.assertEqual(self.store.task("t1")["state"], "failed")
        self.assertIsNone(self.store.claim("owner"))

    def test_crash_marks_claimed_inbox_uncertain_and_never_replays(self):
        self.ongoing()
        self.store.instruct("t1", "m1", "do original scope")
        self.store.start_session()
        self.store.claim("owner")
        with self.assertRaises(SafetyError):
            Store(self.state).start_session()
        self.assertEqual(self.store.events("t1")[0]["disposition"], "uncertain")
        self.store.recover("Workers stopped and outputs inspected")
        self.assertIsNone(self.store.claim("owner"))

    def test_resume_argv_preserves_sandbox_and_exact_session(self):
        session = str(uuid.uuid4())
        spec = self.store.validate_spec(self.spec(provider="codex", continuation="owner"))
        spec["_session_id"] = session
        args = CLIAdapter("codex", "/trusted/codex").command(spec)
        self.assertLess(args.index("--sandbox"), args.index("resume"))
        self.assertLess(args.index('approval_policy="never"'), args.index("resume"))
        self.assertEqual(args[args.index("resume") + 1], session)
        self.assertNotIn("--last", args)
        self.assertNotIn("--ephemeral", args)
        spec.update(provider="claude", model="opus")
        args = CLIAdapter("claude", "/trusted/claude").command(spec)
        self.assertEqual(args[args.index("--resume") + 1], session)
        self.assertIn("--safe-mode", args)
        settings = json.loads(args[args.index("--settings") + 1])
        self.assertFalse(settings["switchModelsOnFlag"])
        self.assertEqual(settings["fallbackModel"], [])
        self.assertEqual(settings["availableModels"], [spec["model"]])
        self.assertIn("dontAsk", args)
        self.assertNotIn("--no-session-persistence", args)

    def test_pending_input_survives_full_queue(self):
        from dataclasses import replace
        self.store.limits = replace(self.store.limits, queue=1)
        self.ongoing()
        self.finish(self.store.claim("owner"))
        self.queued("other")
        self.store.instruct("t1", "m1", "next")
        self.assertEqual(self.store.task("t1")["state"], "waiting")
        other = self.store.claim("owner")
        self.store.finish("other", "owner", other["attempt"], "completed", "done")
        self.assertEqual(self.store.claim("owner")["id"], "t1")
