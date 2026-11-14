"""Prevent retired stylesheet layers and out-of-date bundles returning."""
import json
import re
from pathlib import Path

from scripts.build_frontend import workbench_content


def test_workbench_bundle_is_current_and_sources_are_unique():
    css = Path('app/static/css')
    manifest = json.loads((css / 'workbench.sources.json').read_text(encoding='utf-8'))
    assert len(manifest['sources']) == len(set(manifest['sources']))
    assert (css / 'workbench.css').read_text(encoding='utf-8') == workbench_content()
    assert not {'app.css', 'crm-customer-list.css', 'auto-prospecting-goodjob.css', 'gsc-monitor-fix.css'}.intersection(manifest['sources'])


def test_workbench_has_one_layout_entry_and_no_inline_style_versions():
    index = Path('app/templates/index.html').read_text(encoding='utf-8')
    styles = re.findall(r'<link[^>]+href="/static/css/([^"?]+)', index)
    assert styles == ['workbench.css', 'ui-themes.css', 'appearance.css', 'mail-send-review.css', 'lead-detail-actions.css', 'contact-outreach-history.css', 'lead-contact-scan.css']
    for path in Path('app/templates/partials').glob('*.html'):
        assert '<style' not in path.read_text(encoding='utf-8'), path


def test_retired_customer_screens_do_not_return_to_bundle():
    css = Path('app/static/css/workbench.css').read_text(encoding='utf-8')
    for selector in ['.company-table', '.customer-preview-dialog', '.contact-record-preview-modal', '.gj-workbench']:
        assert selector not in css
