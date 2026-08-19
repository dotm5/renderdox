import { existsSync, mkdirSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { dirname, extname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repo = resolve(here, "..", "..", "..", "..");
const qrenderdoc = join(repo, "qrenderdoc");
const lucideDir = join(qrenderdoc, "Resources", "modern", "lucide");
const manifest = JSON.parse(readFileSync(join(lucideDir, "manifest.json"), "utf8"));
const resourceHeader = readFileSync(join(qrenderdoc, "Code", "Resources.h"), "utf8");
const qrc = readFileSync(join(qrenderdoc, "Resources", "resources.qrc"), "utf8");

const walk = (directory, extensions) => {
  const files = [];
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) files.push(...walk(path, extensions));
    else if (extensions.has(extname(entry.name).toLowerCase())) files.push(path);
  }
  return files;
};

const resourceNames = [...resourceHeader.matchAll(/RESOURCE_DEF\(([^,]+),\s*"[^"]+\.png"\)/g)].map(
  (match) => match[1].trim(),
);
const resourceNameSet = new Set(resourceNames);
const missingResourceMappings = resourceNames.filter(
  (name) => !Object.prototype.hasOwnProperty.call(manifest.legacy, name),
);
const staleResourceMappings = Object.keys(manifest.legacy).filter((name) => !resourceNameSet.has(name));

const uiFiles = walk(qrenderdoc, new Set([".ui"]));
const uiLegacyReferences = [];
for (const path of uiFiles) {
  const source = readFileSync(path, "utf8");
  for (const match of source.matchAll(/:\/(?!modern\/)([^<"]+)\.png/g)) {
    const leaf = match[1].split(/[\\/]/).at(-1).replace(/@(?:2|3|4)x$/, "");
    uiLegacyReferences.push({ path, resource: leaf });
  }
}
const unmappedUiReferences = uiLegacyReferences.filter(
  ({ resource }) => !Object.prototype.hasOwnProperty.call(manifest.legacy, resource),
);

const sourceFiles = walk(qrenderdoc, new Set([".cpp", ".h"]));
const sourceCalls = [];
for (const path of sourceFiles) {
  const source = readFileSync(path, "utf8");
  for (const match of source.matchAll(/(?:Icons|Pixmaps)::([A-Za-z0-9_]+)/g)) {
    if (match[1] !== "library" && match[1] !== "panel") sourceCalls.push({ path, resource: match[1] });
  }
}
const unmappedSourceCalls = sourceCalls.filter(({ resource }) => !resourceNameSet.has(resource));

const sourceNames = new Set();
for (const map of [manifest.legacy, manifest.settings, manifest.eventBrowser, manifest.panels]) {
  for (const value of Object.values(map)) {
    if (typeof value === "string") sourceNames.add(value);
  }
}
const missingLibrarySources = [...sourceNames].filter(
  (name) => !existsSync(join(lucideDir, `${name}.svg`)),
);
const missingQrcEntries = readdirSync(lucideDir)
  .filter((name) => name.endsWith(".svg") || name === "manifest.json")
  .filter((name) => !qrc.includes(`modern/lucide/${name}`));

const panelBlock = resourceHeader.match(/enum class PanelIcon\s*\{([\s\S]*?)\};/);
const panelCount = panelBlock
  ? panelBlock[1]
      .split(",")
      .map((value) => value.replace(/\/\/.*$/gm, "").trim())
      .filter(Boolean).length
  : 0;

const failures = {
  missingResourceMappings,
  staleResourceMappings,
  unmappedUiReferences,
  unmappedSourceCalls,
  missingLibrarySources,
  missingQrcEntries,
  settingsCountMismatch: Object.keys(manifest.settings).length === 9 ? [] : [Object.keys(manifest.settings).length],
  panelCountMismatch: Object.keys(manifest.panels).length === panelCount ? [] : [panelCount],
};
const passed = Object.values(failures).every((items) => items.length === 0);

const report = {
  schema: 1,
  status: passed ? "PASS" : "FAIL",
  scope: "qrenderdoc executable UI icon consumption paths",
  counts: {
    resourcePngIdentities: resourceNames.length,
    mappedResourceIdentities: Object.keys(manifest.legacy).length,
    lucideSources: sourceNames.size,
    uiFilesScanned: uiFiles.length,
    uiLegacyReferences: uiLegacyReferences.length,
    sourceIconCalls: sourceCalls.length,
    settingsSemantics: Object.keys(manifest.settings).length,
    panelSemantics: Object.keys(manifest.panels).length,
  },
  exclusions: [
    "application logo and topology diagrams are content assets, not command or panel icons",
    "shader debugger cursor/sample/NaN transport glyphs use the documented local redraw fallback",
  ],
  failures,
};

const artifactDir = join(repo, "artifacts", "icon-modernization", "v4");
mkdirSync(artifactDir, { recursive: true });
writeFileSync(join(artifactDir, "exe-icon-audit.json"), `${JSON.stringify(report, null, 2)}\n`, "utf8");
writeFileSync(
  join(artifactDir, "exe-icon-audit.md"),
  `# Executable icon audit\n\n` +
    `Status: **${report.status}**\n\n` +
    `- ${report.counts.resourcePngIdentities} legacy resource identities reviewed and mapped.\n` +
    `- ${report.counts.uiLegacyReferences} designer-file icon references checked across ${report.counts.uiFilesScanned} UI files.\n` +
    `- ${report.counts.sourceIconCalls} C++ icon call sites checked.\n` +
    `- ${report.counts.settingsSemantics} settings navigation semantics and ${report.counts.panelSemantics} panel semantics declared.\n` +
    `- ${report.counts.lucideSources} pinned Lucide source glyphs packaged.\n\n` +
    `The modern theme resolves legacy UI references through the manifest and renders scalable SVG at the target monitor DPR. Specialized shader-debug transport glyphs remain the only local-redraw fallback.\n`,
  "utf8",
);

console.log(JSON.stringify(report.counts));
console.log(`icon audit ${report.status}: ${join(artifactDir, "exe-icon-audit.json")}`);
if (!passed) {
  console.error(JSON.stringify(failures, null, 2));
  process.exitCode = 1;
}
