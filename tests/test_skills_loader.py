from simplified_chatbot.skills.loader import SkillsLoader


def test_skills_loader_lists_builtin_skills():
    loader = SkillsLoader()

    skills = loader.list_skills()

    names = [item["name"] for item in skills]
    assert "concise-writer" in names
    assert "math-tutor" in names
    assert "tool-use-reminder" in names


def test_skills_loader_reads_metadata_and_always_skills():
    loader = SkillsLoader()

    metadata = loader.get_skill_metadata("concise-writer")

    assert metadata is not None
    assert metadata["description"] == "Keep answers concise, direct, and easy to scan."
    assert "concise-writer" in loader.get_always_skills()
