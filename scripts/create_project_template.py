"""Export source code for a new project without local data or credentials.

Run: python -m scripts.create_project_template [--output PATH]
This does not connect to, clear or copy the current database.
"""
import argparse
from pathlib import Path
import zipfile

from scripts.build_frontend import CSS, workbench_content

ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = ('README.md', 'LICENSE', '.gitignore', 'requirements.txt', 'run.py', 'pytest.ini')
SOURCE_DIRS = ('app', 'scripts', 'tests', 'docs')
EXCLUDED_DIRS = frozenset({'__pycache__', '.pytest_cache', 'node_modules', '.venv', 'venv',
                          'uploads', 'exports', 'backups', 'output', 'tmp', '.codex', '.idea',
                          'maintenance', 'archive', 'archives'})
EXTENSIONS = frozenset({'.py', '.js', '.cjs', '.css', '.json', '.html', '.md', '.txt',
                        '.ico', '.svg', '.png', '.jpg', '.jpeg', '.webp', '.woff', '.woff2', '.xlsx'})


def source_files(root: Path):
    for name in ROOT_FILES:
        path = root / name
        if path.is_file() and not path.is_symlink():
            yield path
    for folder in SOURCE_DIRS:
        for path in sorted((root / folder).rglob('*')):
            relative = path.relative_to(root)
            if any(part in EXCLUDED_DIRS for part in relative.parts) or path.is_symlink():
                continue
            if path.suffix.lower() == '.xlsx' and relative.as_posix() != 'app/resources/quotation/cherry-layout.xlsx':
                continue
            if path.is_file() and path.suffix.lower() in EXTENSIONS and not path.name.startswith('.env'):
                yield path


def export_template(root: Path, target: Path) -> int:
    root = root.resolve()
    files = list(source_files(root))
    if target.resolve() in [p.resolve() for p in files]:
        raise ValueError('Template output cannot replace a source file')
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, path.relative_to(root).as_posix())
    return len(files)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'output/tophoo-global-github.zip')
    args = parser.parse_args()
    if not (CSS / 'workbench.css').exists() or (CSS / 'workbench.css').read_text(encoding='utf-8') != workbench_content():
        parser.exit(1, 'Build current styles first: python -m scripts.build_frontend\n')
    count = export_template(ROOT, args.output)
    print(f'Exported {count} source files: {args.output.resolve()}')
    print('Use a new database and a new .env when starting a new project.')


if __name__ == '__main__':
    main()
