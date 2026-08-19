import { readFileSync, mkdirSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const moduleRoot = resolve(process.env.MORPHICONS_NODE_MODULES || join(here, "node_modules"));
const morphiconsPackage = JSON.parse(
  readFileSync(join(moduleRoot, "morphicons", "package.json"), "utf8"),
);
const lucidePackage = JSON.parse(
  readFileSync(join(moduleRoot, "lucide", "package.json"), "utf8"),
);

if (
  morphiconsPackage.version !== "1.7.0" ||
  lucidePackage.version !== "1.28.0"
) {
  throw new Error(
    `Pinned packages required: morphicons 1.7.0 and lucide 1.28.0; got ${morphiconsPackage.version} and ${lucidePackage.version}`,
  );
}

const morphiconsDom = pathToFileURL(
  join(moduleRoot, "morphicons", "dist", "dom.js"),
).href;
const { createMorph } = await import(morphiconsDom);
const sourceName = "maximize";
const targetName = "minimize";
const sourceModule = pathToFileURL(
  join(moduleRoot, "lucide", "dist", "esm", "icons", `${sourceName}.mjs`),
).href;
const targetModule = pathToFileURL(
  join(moduleRoot, "lucide", "dist", "esm", "icons", `${targetName}.mjs`),
).href;
const source = (await import(sourceModule)).default;
const target = (await import(targetModule)).default;

const frameCount = 49;
const minProgress = -0.1;
const maxProgress = 1.1;
const outputDir = resolve(here, "..", "morph", "fit-window");
mkdirSync(outputDir, { recursive: true });

let currentPath = "";
const morph = createMorph(
  {
    setAttribute(name, value) {
      if (name === "d") currentPath = value;
    },
  },
  source,
  { reducedMotion: "always" },
);

const escapeAttribute = (value) =>
  value.replaceAll("&", "&amp;").replaceAll('"', "&quot;").replaceAll("<", "&lt;");

const writeFileIfChanged = (path, contents) => {
  try {
    if (readFileSync(path, "utf8") === contents) return false;
  } catch (error) {
    if (error.code !== "ENOENT") throw error;
  }

  writeFileSync(path, contents, "utf8");
  return true;
};

let writtenFiles = 0;

for (let index = 0; index < frameCount; index++) {
  const progress = minProgress + ((maxProgress - minProgress) * index) / (frameCount - 1);
  morph.seek(target, progress);
  const svg =
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" ' +
    'stroke="#20A76B" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">\n' +
    `  <path d="${escapeAttribute(currentPath)}"/>\n` +
    "</svg>\n";
  writtenFiles += Number(
    writeFileIfChanged(
      join(outputDir, `frame_${String(index).padStart(2, "0")}.svg`),
      svg,
    ),
  );
}

morph.destroy();

const manifest = {
  schema: 1,
  component: "RDToolButton",
  application: "TextureViewer.fitToWindow",
  framePattern: ":/modern/morph/fit-window/frame_%1.svg",
  frameCount,
  progressRange: [minProgress, maxProgress],
  generator: {
    package: "morphicons",
    version: morphiconsPackage.version,
    license: "MIT",
    preset: "snappy",
    spring: { stiffness: 420, damping: 30 },
  },
  icons: {
    library: "Lucide",
    version: lucidePackage.version,
    license: "ISC and MIT (Feather-derived endpoints)",
    source: sourceName,
    target: targetName,
  },
  fallback: {
    unchecked: ":/modern/fallback/arrow_out.svg",
    checked: ":/modern/fallback/arrow_in.svg",
  },
  selectionPolicy:
    "Animate only a single control whose meaning changes between two visible states; keep separate navigation, one-shot actions, passive status, and specialised playback icons static",
};
writtenFiles += Number(
  writeFileIfChanged(
    resolve(here, "..", "morph", "manifest.json"),
    `${JSON.stringify(manifest, null, 2)}\n`,
  ),
);

console.log(
  `verified ${frameCount} Morphicons frames in ${outputDir}; wrote ${writtenFiles} changed files`,
);
