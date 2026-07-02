from pathlib import Path

from stonebranch_graph.tui import TerminalUi
from stonebranch_graph.tui_rendering import next_recommended_action, print_main_dashboard
from stonebranch_graph.tui_settings import TuiSettings


def test_main_dashboard_shows_missing_paths_and_settings_recommendation(capsys) -> None:
    settings = TuiSettings(stonebranch_path="", jil_path="", output_path="")

    print_main_dashboard(settings)

    out = capsys.readouterr().out
    assert "Project dashboard" in out
    assert "Selected folders" in out
    assert "Stonebranch repo:" in out
    assert "MISSING" in out
    assert "JIL repo:" in out
    assert "Output folder:" in out
    assert "Next recommended action" in out
    assert "4) Settings" in out


def test_main_dashboard_recommends_pack_and_compare_steps(tmp_path: Path) -> None:
    sb_source = tmp_path / "sb-source"
    jil_source = tmp_path / "jil-source"
    out_dir = tmp_path / "out"
    sb_pack = out_dir / "stonebranch-pack"
    jil_pack = out_dir / "jil-pack"
    compare_pack = out_dir / "compare-pack"
    sb_source.mkdir()
    jil_source.mkdir()
    out_dir.mkdir()

    settings = TuiSettings(
        stonebranch_path=str(sb_source),
        jil_path=str(jil_source),
        output_path=str(out_dir),
        stonebranch_pack_path=str(sb_pack),
        jil_pack_path=str(jil_pack),
        compare_pack_path=str(compare_pack),
    )

    assert next_recommended_action(settings).startswith("1) Build Stonebranch")

    sb_pack.mkdir(parents=True)
    (sb_pack / "graph.json").write_text("{}", encoding="utf-8")
    assert next_recommended_action(settings).startswith("2) Build JIL")

    jil_pack.mkdir(parents=True)
    (jil_pack / "graph.json").write_text("{}", encoding="utf-8")
    assert next_recommended_action(settings).startswith("3) Compare")

    (compare_pack / "compare").mkdir(parents=True)
    (compare_pack / "compare" / "report.md").write_text("# report", encoding="utf-8")
    assert "Review generated reports" in next_recommended_action(settings)


def test_terminal_ui_run_uses_dashboard_on_main_screen(monkeypatch) -> None:
    ui = TerminalUi()
    calls = []

    monkeypatch.setattr(ui, "clear", lambda: None)
    monkeypatch.setattr(ui, "header", lambda *args, **kwargs: None)
    monkeypatch.setattr(ui, "print_main_dashboard", lambda: calls.append("dashboard"))
    monkeypatch.setattr(ui, "print_main_menu", lambda: calls.append("menu"))
    monkeypatch.setattr(ui, "save_settings", lambda silent=False: calls.append("save"))
    monkeypatch.setattr(ui, "menu_choice", lambda label, valid: "0")

    assert ui.run() == 0
    assert calls == ["dashboard", "menu", "save"]
