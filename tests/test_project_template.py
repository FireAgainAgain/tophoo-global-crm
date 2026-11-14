"""A reusable source template must never carry local business data or secrets."""
import zipfile

import pytest

from scripts.create_project_template import export_template


def test_template_exports_sources_but_not_credentials_or_generated_business_data(tmp_path):
    root = tmp_path / 'project'
    files = {
        'README.md': 'Readme', 'LICENSE': 'MIT', '.env.example': 'MYSQL_PASSWORD=replace-me',
        'pytest.ini': '[pytest]', 'app/resources/quotation/cherry-layout.xlsx': 'required workbook resource',
        '.env': 'PRIVATE_SECRET=must-not-export', 'old.sql': 'private data',
        'app/main.py': '# app', 'app/static/css/workbench.css': 'body{}',
        'app/static/uploads/customer.png': 'private image',
        'app/resources/private.xlsx': 'private workbook',
        'app/__pycache__/main.pyc': 'bytecode', 'app/config/.env.local': 'private',
        'scripts/build_frontend.py': '# build', 'tests/test_sample.py': '# test',
        'docs/PROJECT_TEMPLATE.md': 'Guide', 'docs/maintenance/old.md': 'Old report',
        'backups/database.json': 'private', 'output/export.pdf': 'private',
    }
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')
    target = tmp_path / 'template.zip'
    assert export_template(root, target) == 9
    with zipfile.ZipFile(target) as archive:
        assert set(archive.namelist()) == {
            'README.md', 'LICENSE', 'app/main.py', 'app/static/css/workbench.css',
            'scripts/build_frontend.py', 'tests/test_sample.py', 'docs/PROJECT_TEMPLATE.md',
            'pytest.ini', 'app/resources/quotation/cherry-layout.xlsx',
        }
        assert all(b'must-not-export' not in archive.read(name) for name in archive.namelist())


def test_template_cannot_overwrite_source_file(tmp_path):
    root = tmp_path / 'project'
    root.mkdir()
    source = root / 'README.md'
    source.write_text('keep', encoding='utf-8')
    with pytest.raises(ValueError):
        export_template(root, source)
    assert source.read_text(encoding='utf-8') == 'keep'
