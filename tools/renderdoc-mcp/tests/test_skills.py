import asyncio
import hashlib
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from contracts import PROTOCOL_VERSIONS, ToolError
from contracts.catalog import TOOLS
from server.stdio import StdioServer
from supervisor.service import Service
from workflows.skills import DEFAULT_SKILL, FILES, PREFIX, PROMPT_NAME, SKILL_NAMES, SkillLibrary


class SkillTests(unittest.TestCase):
    def setUp(self):
        self.library = SkillLibrary(ROOT / "skills")

    def test_default_and_complete_bilingual_metadata(self):
        listing = self.library.listing()
        self.assertEqual(listing["defaultSkill"], DEFAULT_SKILL)
        self.assertEqual(listing["defaultLanguage"], "zh-CN")
        self.assertEqual([x["language"] for x in listing["skills"]], ["zh-CN", "en"])
        self.assertEqual([x["default"] for x in listing["skills"]], [True, False])
        for name in SKILL_NAMES:
            for path in FILES:
                item = self.library.get(name, path)
                self.assertEqual(item["sha256"], hashlib.sha256(item["text"].encode()).hexdigest())
                self.assertEqual(item["byteLength"], len(item["text"].encode()))
                self.assertGreater(len(item["text"]), 500)
            entry = self.library.get(name)["text"]
            self.assertTrue(entry.startswith("---\nname: " + name + "\n"))
            for reference in FILES[1:]:
                self.assertIn("(" + reference + ")", entry)

    def test_allowlist_blocks_arbitrary_files_and_traversal(self):
        for name, path in [("unknown", "SKILL.md"), (DEFAULT_SKILL, "../../README.md"),
                           (DEFAULT_SKILL, "references/../SKILL.md"), (DEFAULT_SKILL, "/SKILL.md")]:
            with self.assertRaises(ToolError):
                self.library.get(name, path)
        with self.assertRaises(ToolError):
            self.library.read_resource(PREFIX + DEFAULT_SKILL + "/../../README.md")

    def test_default_is_discovery_not_fixed_effect_coverage(self):
        chinese = self.library.get()["text"]
        english = self.library.get(SKILL_NAMES[1])["text"]
        self.assertIn("启发式发现", chinese)
        self.assertIn("不是必查清单", chinese)
        self.assertIn("不以固定类别覆盖率作为完成条件", chinese)
        self.assertIn("heuristic discovery", english)
        self.assertIn("not required checks", english)
        self.assertIn("Fixed-category coverage is not a completion criterion", english)

    def test_resources_read_all_ten_and_match_tools(self):
        self.assertEqual(len(self.library.resources()), 10)
        for resource in self.library.resources():
            text = self.library.read_resource(resource["uri"])["contents"][0]["text"]
            self.assertIn("# ", text)
        routing = self.library.get(path="references/tool-routing.md")["text"]
        for line in routing.splitlines():
            if line.startswith("| ") and "、" in line:
                for tool in line.split("|")[2].strip().split("、"):
                    self.assertIn(tool, TOOLS)

    def test_relocated_library_has_no_workspace_dependency(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "mcp" / "source" / "skills"
            shutil.copytree(ROOT / "skills", target)
            other = SkillLibrary(target)
            self.assertEqual(other.listing(), self.library.listing())
            for resource in other.resources():
                self.assertEqual(other.read_resource(resource["uri"]), self.library.read_resource(resource["uri"]))

    def test_prompt_language_and_argument_validation(self):
        default = self.library.prompt(PROMPT_NAME, {})
        english = self.library.prompt(PROMPT_NAME, {"language": "en", "objective": "wet skin"})
        self.assertIn("name: game-rendering-analysis\n", default["messages"][0]["content"]["text"])
        self.assertIn("name: game-rendering-analysis-en\n", english["messages"][0]["content"]["text"])
        for args in ({"language": "fr"}, {"objective": 1}, {"arbitrary": "x"}, []):
            with self.assertRaises(ToolError):
                self.library.prompt(PROMPT_NAME, args)
        with self.assertRaises(ToolError):
            self.library.prompt("missing", {})

    def test_service_tools_do_not_start_native_worker(self):
        async def run():
            with tempfile.TemporaryDirectory() as folder:
                service = Service(folder, ROOT, sys.executable, Path(folder) / "output")
                try:
                    self.assertEqual((await service.call("list_analysis_skills", {}))["defaultLanguage"], "zh-CN")
                    self.assertEqual((await service.call("get_analysis_skill", {}))["language"], "zh-CN")
                    self.assertEqual((await service.call("get_analysis_skill", {"name": SKILL_NAMES[1]}))["language"], "en")
                    self.assertFalse(service.workers)
                    self.assertFalse(service.sessions)
                finally:
                    await service.close()
        asyncio.run(run())

    def test_protocol_discovery_for_both_supported_versions(self):
        async def run():
            for version in PROTOCOL_VERSIONS:
                server = StdioServer.__new__(StdioServer)
                server.service = SimpleNamespace(analysis_skills=self.library, db={"artifacts": {}})
                server.initialized = False
                init = await server.dispatch("initialize", {"protocolVersion": version})
                self.assertEqual(init["protocolVersion"], version)
                self.assertIn("prompts", init["capabilities"])
                self.assertIn("Chinese", init["instructions"])
                server.initialized = True
                self.assertEqual(len((await server.dispatch("resources/list", {}))["resources"]), 10)
                self.assertEqual((await server.dispatch("prompts/list", {}))["prompts"][0]["name"], PROMPT_NAME)
                for resource in self.library.resources():
                    self.assertIn("text", (await server.dispatch("resources/read", {"uri": resource["uri"]}))["contents"][0])
                prompt = await server.dispatch("prompts/get", {"name": PROMPT_NAME})
                self.assertIn("name: game-rendering-analysis\n", prompt["messages"][0]["content"]["text"])
        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
