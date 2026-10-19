import { writeStorageConfig } from "./storage-config.mjs";
import path from "node:path";
import { fileURLToPath } from "node:url";

function parseArgs(argv) {
  const options = {};
  for (let index = 0; index < argv.length; index += 1) {
    const flag = argv[index];
    if (flag === "--help") return { help: true };
    if (flag !== "--wiki-root") {
      throw new Error(`unknown option: ${flag}`);
    }
    const value = argv[index + 1];
    if (!value || value.startsWith("--")) {
      throw new Error(`${flag} requires a value`);
    }
    options.wikiroot = value;
    index += 1;
  }
  if (!options.wikiroot) throw new Error("--wiki-root is required");
  return options;
}

function printHelp() {
  process.stdout.write(
    "Usage: node scripts/configure-storage.mjs --wiki-root <absolute-path>\n",
  );
}

export async function main(argv = process.argv.slice(2)) {
  try {
    const options = parseArgs(argv);
    if (options.help) {
      printHelp();
      return 0;
    }
    const config = await writeStorageConfig({
      wikiRoot: options.wikiroot,
    });
    process.stdout.write(`${JSON.stringify(config)}\n`);
    return 0;
  } catch (error) {
    process.stderr.write(`SelfOpenWiki storage config error: ${error.message}\n`);
    return 2;
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  process.exitCode = await main();
}
