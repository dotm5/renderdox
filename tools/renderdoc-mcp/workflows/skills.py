"""Curated, portable analysis skills exposed over tools, resources and prompts."""
import hashlib
import json
from pathlib import Path

from contracts import ToolError

DEFAULT_SKILL = "game-rendering-analysis"
SKILL_NAMES = (DEFAULT_SKILL, "game-rendering-analysis-en")
FILES = ("SKILL.md", "references/tool-routing.md", "references/replay-experiments.md",
         "references/article-format.md", "references/capability-audit.md")
PREFIX = "renderdoc://skills/"
PROMPT_NAME = "analyze_game_rendering"


class SkillLibrary:
    def __init__(self, root):
        self.root = Path(root).resolve()

    def get(self, name=DEFAULT_SKILL, path="SKILL.md"):
        if name not in SKILL_NAMES or path not in FILES:
            raise ToolError("missing_analysis_skill", "Unknown bundled skill or reference")
        file = (self.root / name / path).resolve()
        if not file.is_relative_to(self.root) or not file.is_file():
            raise ToolError("skill_unavailable", "Bundled skill file is missing")
        data = file.read_bytes()
        return {"name": name, "language": "en" if name.endswith("-en") else "zh-CN",
                "default": name == DEFAULT_SKILL, "path": path, "uri": PREFIX + name + "/" + path,
                "mimeType": "text/markdown", "byteLength": len(data),
                "sha256": hashlib.sha256(data).hexdigest(), "text": data.decode("utf-8")}

    def listing(self):
        entries = []
        for name in SKILL_NAMES:
            item = self.get(name)
            front = item["text"].split("---", 2)[1]
            metadata = dict(line.split(":", 1) for line in front.splitlines() if ":" in line)
            entries.append({"name": name, "description": metadata["description"].strip(),
                            "language": item["language"], "default": item["default"],
                            "uri": item["uri"], "sha256": item["sha256"],
                            "references": [{"path": path, "uri": PREFIX + name + "/" + path} for path in FILES[1:]]})
        return {"defaultSkill": DEFAULT_SKILL, "defaultLanguage": "zh-CN", "skills": entries}

    def resources(self):
        return [{"uri": PREFIX + name + "/" + path, "name": name + "/" + path,
                 "description": ("默认中文 TA 分析 skill" if name == DEFAULT_SKILL else "English analysis skill")
                                + (" entry" if path == "SKILL.md" else " reference"),
                 "mimeType": "text/markdown"} for name in SKILL_NAMES for path in FILES]

    def read_resource(self, uri):
        allowed = {item["uri"] for item in self.resources()}
        if uri not in allowed:
            raise ToolError("missing_analysis_skill", "Unknown skill resource URI")
        name, path = uri[len(PREFIX):].split("/", 1)
        item = self.get(name, path)
        return {"contents": [{"uri": uri, "mimeType": "text/markdown", "text": item["text"]}]}

    def prompts(self):
        return {"prompts": [{"name": PROMPT_NAME,
                "description": "Use the bundled LLM rendering-analysis skill; Chinese TA workflow by default, English optional.",
                "arguments": [{"name": "objective", "description": "Analysis question or requested effects", "required": False},
                              {"name": "captureId", "description": "Optional saved capture identity", "required": False},
                              {"name": "language", "description": "zh-CN (default) or en", "required": False}]}]}

    def prompt(self, name, args):
        if name != PROMPT_NAME:
            raise ToolError("missing_prompt", str(name))
        if not isinstance(args, dict) or set(args) - {"objective", "captureId", "language"} or any(not isinstance(v, str) for v in args.values()):
            raise ToolError("invalid_arguments", "Prompt arguments must be supported strings")
        language = args.get("language", "zh-CN")
        if language not in ("zh-CN", "en"):
            raise ToolError("invalid_arguments", "language must be zh-CN or en")
        skill = self.get(DEFAULT_SKILL if language == "zh-CN" else "game-rendering-analysis-en")
        text = skill["text"] + "\n\nTask context (JSON data):\n" + json.dumps(args, ensure_ascii=False)
        return {"description": "LLM-led, evidence-backed rendering analysis (" + language + ")",
                "messages": [{"role": "user", "content": {"type": "text", "text": text}}]}
