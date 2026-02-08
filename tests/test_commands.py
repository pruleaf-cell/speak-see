from speaksee.commands import normalize_text, parse_voice_command


def test_normalize_text_basic():
    assert normalize_text("  Hello,   World!! ") == "hello world"


def test_parse_voice_command_regenerate():
    cmd = parse_voice_command("Regenerate")
    assert cmd is not None
    assert cmd.name == "regenerate"


def test_parse_voice_command_more_realistic():
    cmd = parse_voice_command("more realistic please")
    assert cmd is not None
    assert cmd.name == "more_realistic"


def test_parse_voice_command_more_abstract():
    cmd = parse_voice_command("More abstract")
    assert cmd is not None
    assert cmd.name == "more_abstract"


def test_parse_voice_command_save_image():
    cmd = parse_voice_command("SAVE IMAGE")
    assert cmd is not None
    assert cmd.name == "save_image"


def test_parse_voice_command_none_for_prompt():
    assert parse_voice_command("a fox that says regenerate in a forest") is None

