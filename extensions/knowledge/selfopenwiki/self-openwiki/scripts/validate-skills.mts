import { readFile, readdir } from "node:fs/promises";
import path from "node:path";

const repositoryRoot = path.resolve(import.meta.dirname, "..");
const roots = [path.join(repositoryRoot, "openwiki-skills")];
const optionalAgentRoot = path.join(repositoryRoot, "agent-skills");
try {
  await readdir(optionalAgentRoot);
  roots.push(optionalAgentRoot);
} catch {}

let count = 0;
for (const root of roots) {
  for (const entry of await readdir(root, { withFileTypes: true })) {
    if (!entry.isDirectory() || entry.isSymbolicLink()) {
      throw new Error("Skill roots may contain only regular package directories.");
    }
    const skillRoot = path.join(root, entry.name);
    const markdown = await readFile(path.join(skillRoot, "SKILL.md"), "utf8");
    const frontmatter = /^---\r?\n([\s\S]+?)\r?\n---\r?\n/u.exec(markdown);
    if (!frontmatter) throw new Error(`Skill ${entry.name} has no front matter.`);
    if (!/^name:\s*[a-z0-9][a-z0-9-]*\s*$/mu.test(frontmatter[1]!)) {
      throw new Error(`Skill ${entry.name} has an invalid name.`);
    }
    if (!/^description:\s*(?:>|\S)/mu.test(frontmatter[1]!)) {
      throw new Error(`Skill ${entry.name} has no description.`);
    }
    for (const match of markdown.matchAll(/references\/[A-Za-z0-9._/-]+\.md/gu)) {
      await readFile(path.join(skillRoot, ...match[0].split("/")));
    }
    const agent = await readFile(path.join(skillRoot, "agents", "openai.yaml"), "utf8");
    if (!/display_name:\s*"[^"]+"/u.test(agent)) {
      throw new Error(`Skill ${entry.name} has invalid agent metadata.`);
    }
    count += 1;
  }
}
if (count === 0) throw new Error("No C7 Skill package was validated.");
process.stderr.write(`Validated ${count} C7 Skill package(s).\n`);
