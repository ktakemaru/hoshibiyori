"""Claude Code プラグイン定義(.claude-plugin/ と skills/hoshibiyori/SKILL.md)の整合テスト。通信しない・標準ライブラリのみ。

公式の検証(claude plugin validate)の代わりではなく、リポジトリ側で崩れやすい点(名前の一致・予約名・SKILL.md の上限・参照先の実在)を CI でも見る。
"""
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLUGIN_JSON = ROOT / ".claude-plugin" / "plugin.json"
MARKETPLACE_JSON = ROOT / ".claude-plugin" / "marketplace.json"
SKILL_MD = ROOT / "skills" / "hoshibiyori" / "SKILL.md"

DESCRIPTION_LIMIT = 1536       # description + when_to_use の上限(公式: スキル一覧での切り詰め)
BODY_LINE_LIMIT = 500          # SKILL.md は500行未満(公式の推奨)
RESERVED_PREFIXES = ("claude-", "anthropic-", "anthropics-", "cc-plugin-")
RESERVED_NAMES = {"claude", "anthropic", "anthropics", "claude-code", "claude-mods"}
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")   # マーケットプレイス名・プラグイン名に使える文字(公式)


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def parse_skill(path):
    """frontmatter(name / description / when_to_use / allowed-tools のリスト)と本文を返す。簡易パーサ(YAMLライブラリ不要)。"""
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    assert text.startswith("---\n"), "frontmatter がない"
    head, body = text[4:].split("\n---\n", 1)
    fm, key = {}, None
    for line in head.split("\n"):
        m = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", line)
        if m:
            key, val = m.group(1), m.group(2).strip()
            if val.startswith("'") and val.endswith("'") and len(val) >= 2:
                val = val[1:-1].replace("''", "'")
            fm[key] = val if val else []
        elif line.startswith("  - ") and isinstance(fm.get(key), list):
            fm[key].append(line[4:].strip())
        elif line.strip():
            raise AssertionError(f"解釈できない frontmatter の行: {line!r}")
    return fm, body


class JsonTest(unittest.TestCase):
    def test_both_json_are_valid(self):
        for p in (PLUGIN_JSON, MARKETPLACE_JSON):
            with self.subTest(p=p.name):
                self.assertIsInstance(load_json(p), dict)

    def test_plugin_json_fields(self):
        d = load_json(PLUGIN_JSON)
        self.assertEqual(d["name"], "hoshibiyori")
        for k in ("displayName", "version", "description", "author", "license", "keywords"):
            self.assertIn(k, d)
        self.assertTrue(d["author"].get("name"))
        self.assertEqual(d["license"], "MIT")
        self.assertRegex(d["version"], r"^\d+\.\d+\.\d+$")

    def test_marketplace_fields(self):
        m = load_json(MARKETPLACE_JSON)
        for k in ("name", "owner", "plugins"):
            self.assertIn(k, m)
        self.assertTrue(m["owner"].get("name"))
        self.assertEqual(len(m["plugins"]), 1)

    def test_entry_name_matches_plugin_json_and_source_is_root(self):
        entry = load_json(MARKETPLACE_JSON)["plugins"][0]
        self.assertEqual(entry["name"], load_json(PLUGIN_JSON)["name"])
        self.assertEqual(entry["source"], "./")

    def test_names_are_valid_and_not_reserved(self):
        names = {"plugin": load_json(PLUGIN_JSON)["name"], "marketplace": load_json(MARKETPLACE_JSON)["name"],
                 "entry": load_json(MARKETPLACE_JSON)["plugins"][0]["name"]}
        for label, n in names.items():
            with self.subTest(label=label):
                self.assertRegex(n, ID_RE)
                self.assertFalse(n.lower().startswith(RESERVED_PREFIXES), n)
                self.assertNotIn(n.lower(), RESERVED_NAMES)
        self.assertRegex(names["plugin"], r"^[a-z0-9]+(-[a-z0-9]+)*$")  # kebab-case(公式の推奨)

    def test_only_manifests_inside_dot_claude_plugin(self):
        self.assertEqual(sorted(p.name for p in (ROOT / ".claude-plugin").iterdir()), ["marketplace.json", "plugin.json"])


class SkillTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fm, cls.body = parse_skill(SKILL_MD)
        cls.text = SKILL_MD.read_text(encoding="utf-8")

    def test_frontmatter_has_name_and_description(self):
        self.assertEqual(self.fm["name"], "hoshibiyori")
        self.assertTrue(self.fm["description"])

    def test_skill_name_matches_directory(self):
        self.assertEqual(self.fm["name"], SKILL_MD.parent.name)

    def test_description_starts_with_trigger_phrases(self):
        head = self.fm["description"][:120]
        self.assertIn("今週末の星空撮影に適した場所は", head)
        for phrase in ("◯◯の星空", "天の川はいつ見える", "星景撮影の天気", "星空ガイドを作って"):
            self.assertIn(phrase, self.fm["description"])

    def test_description_plus_when_to_use_within_limit(self):
        total = len(self.fm["description"]) + len(self.fm.get("when_to_use", ""))
        self.assertLessEqual(total, DESCRIPTION_LIMIT, total)

    def test_under_500_lines(self):
        self.assertLess(len(self.text.splitlines()), BODY_LINE_LIMIT)

    def test_paths_under_plugin_root_exist(self):
        refs = set(re.findall(r"\$\{CLAUDE_PLUGIN_ROOT\}/([A-Za-z0-9_./-]+)", self.text))
        self.assertTrue(refs)
        for r in refs:
            with self.subTest(ref=r):
                self.assertTrue((ROOT / r).exists(), r)

    def test_backticked_repo_files_exist(self):
        refs = set(re.findall(r"`([A-Za-z0-9_./-]+\.(?:py|md|txt))`", self.text))
        for r in refs:
            with self.subTest(ref=r):
                self.assertTrue((ROOT / r).exists() or (SKILL_MD.parent / r).exists(), r)

    def test_references_dir_links_exist(self):
        for r in set(re.findall(r"\(?(references/[A-Za-z0-9_./-]+)", self.text)):
            with self.subTest(ref=r):
                self.assertTrue((SKILL_MD.parent / r).exists(), r)

    def test_tells_to_read_agents_md_first_and_is_a_thin_layer(self):
        self.assertIn("${CLAUDE_PLUGIN_ROOT}/AGENTS.md", self.text)
        self.assertLess(self.text.index("/AGENTS.md` を Read"), self.text.index("## 1."))
        for sec in ("§10", "§11", "§12"):
            self.assertIn(sec, self.text)

    def test_both_shell_forms_documented(self):
        self.assertIn('HOSHIBIYORI_DATA_DIR="${CLAUDE_PLUGIN_DATA}" python3 -B -X utf8', self.text)
        self.assertIn('$env:HOSHIBIYORI_DATA_DIR="${CLAUDE_PLUGIN_DATA}"; py -B -X utf8', self.text)

    def test_allowed_tools_are_read_only_no_network(self):
        tools = self.fm["allowed-tools"]
        self.assertTrue(tools)
        for t in tools:
            with self.subTest(t=t):
                self.assertTrue(t.startswith("Bash("))
                self.assertIn(" -B -X utf8 ", t)  # プラグイン側に __pycache__ を書かせない
                for banned in ("generate_report", "explore_hoshibiyori", "--network", "--allow-network", "pip", "git "):
                    self.assertNotIn(banned, t)
        # check_setup は引数なしの完全一致(--network を許可しない)
        setup = [t for t in tools if "check_setup.py" in t]
        self.assertEqual(len(setup), 1)
        self.assertTrue(setup[0].endswith('check_setup.py")'))


class VersionTest(unittest.TestCase):
    def test_changelog_top_entry_matches_plugin_version(self):
        """CHANGELOG.md の最新の項(## [x.y.z])と plugin.json の version が一致する(上げ忘れ防止)。"""
        text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        top = re.search(r"^## \[(\d+\.\d+\.\d+)\]", text, re.M)
        self.assertIsNotNone(top)
        self.assertEqual(top.group(1), load_json(PLUGIN_JSON)["version"])


if __name__ == "__main__":
    unittest.main()
