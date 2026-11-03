"""Megjelenések: a beépített Azure/Forest témák és a színsémák."""
import os

import pytest

import Keprename5video as m


def test_groups_cover_every_appearance_once():
    flat = [n for g in m.APPEARANCE_GROUPS for n in g]
    assert len(flat) == len(set(flat)) and tuple(flat) == m.APPEARANCES
    # A "system" kivételével mindegyiknek van palettája
    assert set(m.APPEARANCES) - {"system"} == set(m.PALETTES)


def test_bundled_tcl_themes_present_with_license():
    for name, (path, theme) in m.TCL_THEMES.items():
        full = m.resource_path(path)
        assert os.path.isfile(full), path
        assert os.path.isfile(os.path.join(os.path.dirname(full), "LICENSE"))
        assert m.appearance_available(name)
        # A téma nem írhatja át a program betűtípusát
        with open(full, encoding="utf-8") as f:
            code = f.read()
        code = "\n".join(l for l in code.splitlines() if not l.lstrip().startswith("#"))
        assert "option add *font" not in code and theme in code


def test_tcl_theme_missing_falls_back(monkeypatch, tmp_path):
    monkeypatch.setattr(m, "resource_path", lambda p: str(tmp_path / p))
    assert not m.appearance_available("azure-dark")
    assert m.normalize_appearance("azure-dark") == "system"
    assert m.normalize_appearance("nord") == "nord"


@pytest.mark.parametrize("name, dark", [
    ("system", False), ("flat-light", False), ("flat-dark", True), ("azure-dark", True),
    ("forest-light", False), ("nord", True), ("dracula", True), ("solarized-light", False),
    ("solarized-dark", True), ("midnight", True), ("mint", False),
])
def test_appearance_is_dark(name, dark):
    assert m.appearance_is_dark(name) is dark


def test_switch_through_all_appearances(app):
    for name in m.APPEARANCES:
        if not m.appearance_available(name, m.sv_ttk is not None):
            continue
        app.apply_appearance(name)
        assert app.appearance == name
        assert app.appearance_var.get() == name
        if name in m.TCL_THEMES:
            assert app.style.theme_use() == m.TCL_THEMES[name][1]
            # Az Azure a közös háttérszínt csak a set_theme-ben adná meg; nálunk a palettából jön
            assert app.style.lookup(".", "background") == m.PALETTES[name]["bg"]
        elif name in m.PALETTES and name not in m.SV_APPEARANCES:
            assert app.style.theme_use() == "clam"
        assert app.grid_view.canvas.cget("background") == m.appearance_colors(name)["canvas"]
    # Vissza a rendszerre: a gép saját ttk témája
    app.apply_appearance("system")
    assert app.style.theme_use() == app._native_ttk_theme


def test_appearance_menu_has_separators(app):
    menu = app.nametowidget(app.cget("menu"))
    found = None
    for i in range(menu.index("end") + 1):
        if menu.type(i) == "cascade":
            sub = app.nametowidget(menu.entrycget(i, "menu"))
            for j in range(sub.index("end") + 1):
                if sub.type(j) == "cascade" and sub.entrycget(j, "label") == app.t("menu_appearance"):
                    found = app.nametowidget(sub.entrycget(j, "menu"))
    assert found is not None
    types = [found.type(k) for k in range(found.index("end") + 1)]
    assert types.count("separator") == len(m.APPEARANCE_GROUPS) - 1
    assert types.count("radiobutton") == len(m.APPEARANCES)
