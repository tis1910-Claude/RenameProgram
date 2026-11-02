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


def test_panel_buttons_run_the_feature(app, monkeypatch):
    pump(app, 0.3)
    assert list(app.feature_buttons) == [f.key for f in m.FEATURES]
    for key, btn in app.feature_buttons.items():
        assert btn.winfo_ismapped(), key
        assert btn.winfo_rootx() < app.grid_view.winfo_rootx()  # a rácstól balra
    calls = []
    monkeypatch.setattr(m.messagebox, "showinfo", lambda *a, **k: calls.append(a))
    app.feature_buttons["rename"].invoke()  # nincs kijelölés -> tájékoztatás
    assert calls and calls[-1][1] == app.t("none_selected")


def test_feature_buttons_follow_busy_state(app):
    app.set_busy(True)
    assert all(str(b.cget("state")) == "disabled" for b in app.feature_buttons.values())
    app.set_busy(False)
    assert all(str(b.cget("state")) == "normal" for b in app.feature_buttons.values())


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
