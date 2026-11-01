"""Static skill-contract checks, not claims about live model instruction-following."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
SKILL = (ROOT / '.claude/skills/delegate/SKILL.md').read_text()
PLAN = (ROOT / '.claude/skills/delegate/templates/delegate-plan.md').read_text()
README = (ROOT / 'README.md').read_text()


class PolicyContractTests(unittest.TestCase):
    def test_routing_examples_cover_unknown_usage_and_approval_boundaries(self):
        examples = {
            'Plan-only; score 9; usage 80%; auto-Codex yes': 'Plan only; no workers or Codex',
            'Execute; score 5; usage unknown; Claude scope clear': 'Summary then normal full-Claude parallel work; usage unobserved',
            'Execute; score 7; usage unknown; approval missing': 'Show plan and wait for approval',
            'Execute; score 5; usage 80%; matching auto-Codex opt-in': 'Validate handoff then auto-Codex; no repeat consent',
            'Execute; score 5; usage 80%; auto-Codex no or revoked': 'Ask before Codex; preserve progress',
            'Execute; score 5; usage unknown; auto-Codex yes': 'Normal Claude workflow; no invented threshold trigger',
        }
        for scenario, behavior in examples.items():
            with self.subTest(scenario=scenario):
                self.assertIn(f'| {scenario} | {behavior} |', SKILL)
        self.assertIn('Multiple workers alone do not add an approval gate.', SKILL)
        self.assertIn('normal full-Claude orchestration', README)

    def test_auto_codex_is_per_job_explicit_revocable_and_off_by_default(self):
        self.assertIn('Auto-Codex at ≥70%: no', PLAN)
        self.assertIn('Opt-in evidence / approved by user at: none', PLAN)
        self.assertIn('Approved runtime: exec | interactive; sandbox:', PLAN)
        self.assertIn('expires with the job and can be revoked', SKILL)
        self.assertIn('Plan-only always overrides it.', SKILL)
        self.assertIn('only after an explicit user opt-in', SKILL)
        self.assertIn('without repeat consent', SKILL)

    def test_hard_implementation_has_an_explicit_opus_writer(self):
        self.assertIn('| Hard/risky implementation | delegate-implementer with explicit `model: opus` |', SKILL)
        self.assertIn('Never send implementation to the read-only', SKILL)
        implementer = (ROOT / '.claude/agents/delegate-implementer.md').read_text()
        self.assertIn('tools: Read, Grep, Glob, Bash, Edit, Write', implementer)
        self.assertIn('explicit `model: opus` override', implementer)
        self.assertIn('delegate-implementer with `model: opus`', README)

    def test_tools_are_useful_but_shell_preapproval_is_helper_scoped(self):
        header = SKILL.split('---', 2)[1]
        tools = [line.strip()[2:] for line in header.splitlines() if line.strip().startswith('- ')]
        self.assertEqual(set(tools[:6]), {'Read', 'Grep', 'Glob', 'Agent', 'Edit', 'Write'})
        self.assertEqual(set(tools[6:]), {
            f'Bash(bash ${{CLAUDE_SKILL_DIR}}/scripts/{name}.sh *)'
            for name in ('write-handoff', 'handoff-to-codex', 'review-git')
        })
        reviewer = (ROOT / '.claude/agents/delegate-reviewer.md').read_text()
        self.assertIn('tools: Read, Grep, Glob\n', reviewer)
        self.assertNotIn('Bash', reviewer.split('---', 2)[1])
        self.assertIn('review-git.sh', reviewer)

    def test_agent_descriptions_do_not_introduce_unquoted_yaml_colons(self):
        # Guard the simple one-line descriptions we maintain without a YAML dependency.
        for path in (ROOT / '.claude/agents').glob('*.md'):
            with self.subTest(path=path.name):
                header = path.read_text().split('---', 2)[1]
                description = re.search(r'^description: (.+)$', header, re.M).group(1)
                if ': ' in description:
                    self.assertTrue(description.startswith(('"', "'")))
                    self.assertEqual(description[0], description[-1])


if __name__ == '__main__':
    unittest.main()
