"""Keep CRM aligned with the established Tophoo SEO green palette."""

from pathlib import Path


def test_crm_uses_the_seo_primary_green():
    app_css = Path("app/static/css/base.css").read_text(encoding="utf-8-sig").lower()
    shell_css = Path("app/static/css/workspace-shell.css").read_text(encoding="utf-8-sig").lower()
    login_css = Path("app/static/css/login.css").read_text(encoding="utf-8-sig").lower()

    assert "--primary: #16754f" in app_css
    assert "--login-green:#16754f" in login_css
    assert "--primary:#16754f" in shell_css


def test_crm_specific_pages_do_not_restore_the_old_blue_brand_color():
    crm_styles = "\n".join(
        path.read_text(encoding="utf-8-sig").lower()
        for path in Path("app/static/css").glob("crm-*.css")
    )
    assert "#315f91" not in crm_styles


def test_accent_generation_preserves_semantic_states_and_neutral_surfaces():
    from scripts import build_ui_themes as themes

    source = ':root{--success:#16754f;--primary:#16754f}.notice.success{color:#16754f;background:#eaf5ef}.surface{background:#f4f7f5;color:#4a5c52}.button.primary{background:#16754f;color:#fff}.comm-status.is-working{background:#eef7f2;color:#458366}'
    old_scope, old_hue = themes.SCOPE, themes.HUE
    try:
        output = []
        for name, hue in [('green',155),('blue',217),('purple',262)]:
            themes.SCOPE = f'html[data-ui-theme="{name}"]'
            themes.HUE = hue / 360
            css = themes.overrides(source)
            assert '--success:#16754f' in css
            assert '.notice.success{color:#16754f;background:#eaf5ef}' in css
            assert 'color:#fff' in css
            assert '.comm-status.is-working{background:#eef7f2;color:#458366}' in css
            output.append(css.split('.surface{')[1].split('}')[0])
        assert len(set(output)) == 1, 'Reading colors must not change with the accent'
    finally:
        themes.SCOPE, themes.HUE = old_scope, old_hue
