from simplified_chatbot.skills.loader import SkillsLoader


def test_skills_loader_lists_builtin_skills():
    loader = SkillsLoader()

    skills = loader.list_skills()

    names = [item["name"] for item in skills]
    assert names == ["agent-browser"]


def test_skills_loader_reads_metadata_and_always_skills():
    loader = SkillsLoader()

    metadata = loader.get_skill_metadata("agent-browser")

    assert metadata is not None
    assert metadata["description"] == (
        "Core agent-browser usage guide. Read this before running any agent-browser "
        "commands. Covers the snapshot-and-ref workflow, navigating pages, interacting "
        "with elements (click, fill, type, select), extracting text and data, taking "
        "screenshots, managing tabs, handling forms and auth, waiting for content, "
        "running multiple browser sessions in parallel, and troubleshooting common "
        "failures. Use when the user asks to interact with a website, fill a form, "
        "click something, extract data, take a screenshot, log into a site, test a "
        "web app, or automate any browser task."
    )
    assert "agent-browser" in loader.get_always_skills()
