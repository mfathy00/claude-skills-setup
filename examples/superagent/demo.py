"""Offline continuing-ticket + folder-factory demo. No clients/network/containers."""
import asyncio
import json
from pathlib import Path
import tempfile

from superagent.adapters import MockAdapter, Outcome
from superagent.factory import load_policy, manifest, watch_once, factory_status
from superagent.runtime import Runner
from superagent.safety import encoded
from superagent.state import Store


class RecallDemo(MockAdapter):
    def __init__(self, reference):
        self.reference = reference
        self.turn = 0

    async def run(self, spec, prompt, cancelled, shutdown, limit):
        self.turn += 1
        report = {'status': 'recall', 'summary': 'Fetch this delivered evidence', 'recall': [self.reference]} if self.turn == 1 else {'status': 'ready', 'summary': 'Reviewed recalled evidence'}
        return Outcome('completed', encoded({'mock': True, 'result': encoded(report)}), session_id=spec['_session_id'])


def main():
    with tempfile.TemporaryDirectory(prefix='superagent-demo-') as temporary:
        base = Path(temporary).resolve()
        workspace = base / 'workspace'
        workspace.mkdir()
        (workspace / 'src').mkdir()
        (workspace / 'tests').mkdir()
        store = Store.initialize(base / 'private', workspace, 'example/demo')
        spec = {'id': 'ongoing', 'project': 'demo', 'goal': 'Inspect issue 7 evidence', 'acceptance': 'Return a bounded report',
                'provider': 'mock', 'workspace': str(workspace), 'paths': ['src'], 'continuation': 'subscribed',
                'subject': 'issue:7', 'subscriptions': ['issue_comment'], 'budget_cents': 0}
        store.create_task(spec)
        store.approve('ongoing', 'Offline mock-only continuing mandate')
        asyncio.run(Runner(store).run(True))
        assert store.task('ongoing')['state'] == 'waiting'
        original_session = store.task('ongoing')['session_id']
        store.ingest('event-1', 'issue_comment', {'repository': {'full_name': 'example/demo'}, 'issue': {'number': 7},
                                               'comment': {'body': 'Untrusted issue context, not execution authority'}})
        store.instruct('ongoing', 'owner-1', 'Consider the delivered evidence without expanding scope')
        ref = store.events('ongoing')[0]['ref']
        asyncio.run(Runner(store, adapters={'mock': RecallDemo(ref)}).run(True))
        assert store.task('ongoing')['state'] == 'completed'
        assert store.task('ongoing')['session_id'] == original_session
        store.accept('ongoing', 'Owner reviewed mock output only')
        store.create_task(dict(spec, id='stopped'))
        store.approve('stopped', 'Offline mock only')
        asyncio.run(Runner(store).run(True))
        store.cancel('stopped')
        store.ingest('event-2', 'issue_comment', {'repository': {'full_name': 'example/demo'}, 'issue': {'number': 7}, 'comment': {'body': 'Must not reopen cancelled ticket'}})
        assert store.task('stopped')['state'] == 'cancelled'

        folder = base / 'backlog'
        folder.mkdir()
        item = {'id': 'item-1', 'title': 'Example scoped change', 'description': 'Mock build only',
                'acceptance': 'Demonstrate ordered plan/build/check/security gates', 'dependencies': [], 'ready': True}
        (folder / 'item-1.json').write_text(encoded(item))
        policy = {'id': 'demo-batch', 'backlog_id': 'demo-board', 'folder': str(folder), 'project': 'demo',
                  'selected_ids': ['item-1'], 'workspaces': {'item-1': str(workspace)}, 'paths': ['src', 'tests'],
                  'profiles': {'routine': {'provider': 'mock', 'model': 'mock-routine', 'tier': 'routine'},
                               'strong': {'provider': 'mock', 'model': 'mock-strong', 'tier': 'strong'}},
                  'routing': {'plan': 'strong', 'build': 'routine', 'security': 'strong'}, 'risk_by_item': {'item-1': 'routine'},
                  'checks': ['git-diff-check'], 'approved_hashes': {i['id']: i['content_hash'] for i in manifest(folder)['items']}}
        policy_file = base / 'policy.json'
        policy_file.write_text(encoded(policy))
        policy = load_policy(store, policy_file)
        watch_once(store, policy, True, 'Approve only this exact mock item revision and frozen profiles')
        asyncio.run(Runner(store).run(True))
        packet = factory_status(store, 'demo-batch')
        assert packet['items'][0]['ready_for_owner_review'] and not packet['items'][0]['accepted']
        print(json.dumps({'mode': 'offline mocks only; no model or container invocation',
                          'continuation': {'state': 'accepted', 'same_session': True, 'recall_edges': len(store.graph('ongoing')),
                                           'stopped_ticket': store.task('stopped')['state']},
                          'factory': packet, 'retention': 'Temporary demo state removed on exit'}, indent=2))


if __name__ == '__main__':
    main()
