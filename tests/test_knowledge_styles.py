"""Keep retired knowledge layouts out and isolate the active component styles."""
from pathlib import Path
import re

from scripts.build_ui_themes import blocks, split_selectors


def test_knowledge_styles_only_contain_current_components():
    css = Path('app/static/css/knowledge-library-ui.css').read_text(encoding='utf-8')
    for name in ('script-card', 'script-preview-dialog', 'script-category-notice', 'script-more'):
        assert not re.search(r'\.' + name + r'(?![\w-])', css)


def test_knowledge_rules_are_scoped_including_the_portaled_category_menu():
    css = Path('app/static/css/knowledge-library-ui.css').read_text(encoding='utf-8')

    def check(source):
        for heading, body in blocks(re.sub(r'/\*.*?\*/', '', source, flags=re.S)):
            if heading.startswith(('@media', '@supports')):
                check(body)
            elif not heading.startswith('@'):
                for selector in split_selectors(heading):
                    assert selector.startswith(('.crm-communication-scripts', ':where(.crm-communication-scripts)',
                                                ':where(#knowledge-category-menu)')), selector

    check(css)
