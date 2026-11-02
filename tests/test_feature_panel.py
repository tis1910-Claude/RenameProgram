"""A bal oldali funkcióválasztó panel."""
import Keprename5video as m
from conftest import pump


def test_every_feature_points_to_a_gui_method():
    keys = [f.key for f in m.FEATURES]
    assert keys[:2] == ["daysort", "rename"]  # a kért sorrend: napok szerint, alatta átnevezés
    assert len(set(keys)) == len(keys)
    for feat in m.FEATURES:
        assert callable(getattr(m.ImageRenamerGUI, feat.method, None)), feat.method
        for lang in ("hu", "en"):
            assert feat.title in m.TEXTS[lang] and feat.desc in m.TEXTS[lang]


def test_feature_icon_is_drawn_without_files():
    for feat in m.FEATURES:
        img = m.draw_feature_icon(feat.key, feat.color, size=32)
        assert img.size == (32, 32) and img.mode == "RGBA"
        assert img.getpixel((0, 0))[3] < 40  # lekerekített sarok: (szinte) átlátszó
        r, g, b, a = img.getpixel((4, 16))  # a csempe széle: a funkció színe
        assert a == 255 and (r, g, b) != (255, 255, 255)
        px = img.load()
        whites = sum(1 for x in range(32) for y in range(32) if px[x, y][3] == 255 and min(px[x, y][:3]) > 230)
        assert whites > 20, feat.key  # van fehér jel a csempén
    # rajzoló nélküli (jövőbeli) funkció sem hibázik
    assert m.draw_feature_icon("valami-uj", "#888888").size == (32, 32)


def test_panel_buttons_select_and_start_the_feature(app, monkeypatch):
    pump(app, 0.3)
    assert list(app.feature_buttons) == [f.key for f in m.FEATURES]
    for key, btn in app.feature_buttons.items():
        assert btn.winfo_ismapped(), key
        assert btn.winfo_rootx() < app.grid_view.winfo_rootx()  # a rácstól balra
    # funkció nélkül az első lépések, Indítás gomb nincs
    assert app.t("guide_step_folder") in app.guide_label.cget("text")
    assert not app.guide_run.winfo_ismapped()
    calls = []
    monkeypatch.setattr(app, "rename_selected", lambda: calls.append("rename"))
    app.feature_buttons["rename"].invoke()  # kiválasztás: még nem indul el
    pump(app, 0.2)
    assert app.active_feature == "rename" and calls == []
    assert app.guide_label.cget("text") == app.t("guide_rename")
    assert app.guide_status.cget("text") == app.t("guide_need_folder")
    assert app.guide_run.winfo_ismapped()
    app.guide_run.invoke()
    assert calls == ["rename"]


def test_guide_follows_folder_and_selection(app, tmp_path):
    from conftest import make_jpg
    for i in range(3):
        make_jpg(str(tmp_path / f"k{i}.jpg"), "2023:07:01 10:00:0%d" % i)
    app.folder = str(tmp_path)
    app.load_media()
    pump(app, 0, until=lambda: len(app.files) == 3)
    assert app.t("guide_step_folder_done", folder=tmp_path.name, n=3) in app.guide_label.cget("text")
    app.select_feature("daysort")
    assert app.guide_label.cget("text") == app.t("guide_daysort")
    assert app.guide_status.cget("text") == app.t("guide_selected", n=0)
    app.mark_all()
    pump(app, 0.2)
    assert app.guide_status.cget("text") == app.t("guide_selected", n=3)
    # megjelenésváltás után is kiemelve marad
    app.apply_appearance("flat-dark")
    assert int(app.feature_buttons["daysort"].cget("highlightthickness")) == 2
    assert app.feature_buttons["daysort"].cget("highlightbackground").lower() == m.FEATURE_BY_KEY["daysort"].color


def test_every_feature_has_a_guide():
    for feat in m.FEATURES:
        for lang in ("hu", "en"):
            assert feat.guide in m.TEXTS[lang], (lang, feat.guide)


def test_feature_buttons_follow_busy_state(app):
    app.set_busy(True)
    assert str(app.guide_run.cget("state")) == "disabled"
    app.set_busy(False)
    assert str(app.guide_run.cget("state")) == "normal"


def test_bottom_row_keeps_only_file_actions(app):
    texts = {b.cget("text") for b in app._flow_order}
    assert app.t("btn_rename") not in texts and app.t("btn_daysort") not in texts
    assert app.t("btn_folder") in texts and app.t("btn_delete") in texts


def test_filter_bar_wraps_next_to_panel(app):
    app.geometry("800x600")
    pump(app, 0.5)
    frame_w = app.filter_frame.winfo_width()
    for w in app._filter_groups:
        assert w.winfo_ismapped() and w.winfo_x() + w.winfo_width() <= frame_w
