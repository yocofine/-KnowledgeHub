"""Deployment regressions: native intent prompts must use the site's identity."""
from pathlib import Path
import re
import unittest
from edu.prompt_brand import rebrand_saved_intents

ROOT = Path(__file__).resolve().parents[1]


class PromptBrandTests(unittest.TestCase):
    def test_user_facing_templates_have_no_vendor_identity(self):
        for path in (ROOT / 'config/prompt_templates').glob('*.yaml'):
            with self.subTest(path=path.name):
                text = path.read_text(encoding='utf-8')
                # Technical paths such as .weknora/requirements.json are native
                # protocol identifiers, not the assistant's displayed identity.
                self.assertNotRegex(text, re.compile(r'You are[^\n]*weknora|developed by Tencent', re.I))

    def test_greeting_and_other_intents_keep_native_ids(self):
        text = (ROOT / 'config/prompt_templates/intent_prompts.yaml').read_text(encoding='utf-8')
        self.assertIn('id: "greeting"', text)
        self.assertGreaterEqual(text.count('You are 智导 KnowledgeHub'), 7)
        self.assertIn('{{language}}', text)

    def test_prompt_directory_is_mounted_read_only(self):
        compose = (ROOT / 'edu/compose.yml').read_text(encoding='utf-8')
        self.assertIn('../config/prompt_templates:/app/config/prompt_templates:ro', compose)

    def test_saved_custom_name_and_unrelated_configuration_are_preserved(self):
        source = {'model_id': 'chosen-model', 'system_prompt': '用户自定义业务说明',
                  'intent_prompts': {'greeting': 'You are 智导小助手, an assistant developed by Tencent.\nKeep it brief.\n'}}
        updated = rebrand_saved_intents(source)
        self.assertEqual(updated['intent_prompts']['greeting'], 'You are 智导小助手, an assistant.\nKeep it brief.\n')
        self.assertEqual(updated['system_prompt'], source['system_prompt'])
        self.assertEqual(updated['model_id'], source['model_id'])
        self.assertIn('Tencent', source['intent_prompts']['greeting'])

    def test_only_identity_lines_change_and_migration_is_idempotent(self):
        source = {'intent_prompts': {'greeting': 'You are WeKnora, an assistant developed by Tencent.\nTechnical path: .weknora/settings\n'}}
        updated = rebrand_saved_intents(source)
        self.assertIn('You are 智导 KnowledgeHub, an assistant.', updated['intent_prompts']['greeting'])
        self.assertIn('.weknora/settings', updated['intent_prompts']['greeting'])
        self.assertEqual(rebrand_saved_intents(updated), updated)


if __name__ == '__main__':
    unittest.main()
