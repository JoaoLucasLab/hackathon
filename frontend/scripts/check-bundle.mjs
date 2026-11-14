// AI-02: the built bundle must not contain the Claude API key or call Claude directly.
// Run after `vite build`:  npm run check:bundle
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

const FORBIDDEN = [/sk-ant-[A-Za-z0-9_-]{8,}/, /ANTHROPIC_API_KEY/, /api\.anthropic\.com/];

function files(dir) {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    return statSync(path).isDirectory() ? files(path) : [path];
  });
}

const hits = [];
for (const file of files("dist")) {
  const text = readFileSync(file, "utf8");
  for (const pattern of FORBIDDEN) if (pattern.test(text)) hits.push(`${file}: ${pattern}`);
}
if (hits.length) {
  console.error("Secrets or direct Claude calls found in the bundle:\n" + hits.join("\n"));
  process.exit(1);
}
console.log("Bundle check passed: no API key and no direct Claude calls in dist/.");
