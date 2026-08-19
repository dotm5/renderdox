import { readFileSync, mkdirSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const moduleRoot = resolve(process.env.MORPHICONS_NODE_MODULES || join(here, "node_modules"));
const lucidePackage = JSON.parse(
  readFileSync(join(moduleRoot, "lucide", "package.json"), "utf8"),
);

if (lucidePackage.version !== "1.28.0") {
  throw new Error(`Pinned Lucide 1.28.0 required; got ${lucidePackage.version}`);
}

// The key is the long-standing RenderDoc resource identity. The value is the
// reviewed Lucide semantic replacement used everywhere that legacy resource is
// consumed (designer UI files, actions, menus, item views, tabs, and labels).
// Shader-debug transport controls stay on the local redraw fallback because
// their cursor/sample/NaN meanings do not exist in a general icon library.
const legacy = {
  add: "circle-plus",
  align: "text-align-center",
  arrow_in: "minimize",
  arrow_join: "git-merge",
  arrow_left: "arrow-left",
  arrow_refresh: "refresh-cw",
  arrow_right: "arrow-right",
  arrow_undo: "undo",
  asterisk_orange: "bookmark",
  bug: "bug",
  chart_curve: "chart-line",
  cog: "settings",
  color_wheel: "palette",
  copy: "copy",
  connect: "plug-zap",
  control_base_blue: { fallback: "control_base_blue" },
  control_cursor_blue: { fallback: "control_cursor_blue" },
  control_end_blue: { fallback: "control_end_blue" },
  control_play_blue: { fallback: "control_play_blue" },
  control_nan_blue: { fallback: "control_nan_blue" },
  control_reverse_blue: { fallback: "control_reverse_blue" },
  control_reverse_base_blue: { fallback: "control_reverse_base_blue" },
  control_reverse_cursor_blue: { fallback: "control_reverse_cursor_blue" },
  control_reverse_nan_blue: { fallback: "control_reverse_nan_blue" },
  control_reverse_sample_blue: { fallback: "control_reverse_sample_blue" },
  control_sample_blue: { fallback: "control_sample_blue" },
  control_start_blue: { fallback: "control_start_blue" },
  cross: "circle-x",
  checkerboard: "grid-3x3",
  cut: "scissors",
  del: "trash-2",
  disconnect: "unplug",
  draw_vertex: "triangle",
  find: "search",
  filter: "funnel",
  filter_reapply: "funnel-plus",
  arrow_out: "maximize",
  flag_green: "flag",
  flip_y: "flip-vertical-2",
  folder: "folder",
  folder_page_white: "folder-open",
  help: "circle-question-mark",
  hourglass: "hourglass",
  house: "house",
  information: "info",
  link: "link",
  page_go: "file-up",
  page_white_code: "file-code",
  page_white_database: "database",
  page_white_delete: "file-x",
  page_white_edit: "file-pen-line",
  page_white_link: "file-symlink",
  page_white_stack: "layers",
  paste: "clipboard-paste",
  pixel_history: "rotate-ccw",
  plugin: "puzzle",
  plugin_add: "blocks",
  save: "save",
  text_add: "message-square-plus",
  tick: "circle-check",
  time: "timer",
  timeline_marker: "columns-3",
  upfolder: "folder-up",
  update: "refresh-cw",
  wand: "wand-sparkles",
  wireframe_mesh: "boxes",
  wrench: "wrench",
  zoom: "zoom-in",
  action: "mouse-pointer-click",
  action_hover: "mouse-pointer-click",
  bookmark_blue: "bookmark-check",
};

const settings = {
  general: "sliders-horizontal",
  core: "cpu",
  python: "square-terminal",
  replay: "monitor-play",
  textureViewer: "grid-3x3",
  shaderViewer: "code-xml",
  eventBrowser: "list-tree",
  captureComments: "message-square-text",
  android: "monitor-smartphone",
};

const eventBrowser = {
  previousAction: "arrow-left",
  nextAction: "arrow-right",
  find: "search",
  duration: "timer",
  columns: "columns-3-cog",
  bookmark: "bookmark",
  export: "file-down",
  extensions: "puzzle",
  filter: "funnel",
  filterSettings: "sliders-horizontal",
  edit: "pencil",
  connect: "plug-zap",
  expand: "unfold-vertical",
  collapse: "fold-vertical",
  disable: "circle-x",
  enable: "circle-check",
  reset: "rotate-ccw",
  import: "folder-open",
  delete: "trash-2",
  flag: "flag",
};

// Dock/tab icons describe the panel itself, never the action that opened it.
// Reuse is intentional where the same mental model applies across panels.
const panels = {
  eventBrowser: "list-tree",
  apiInspector: "scan-eye",
  annotation: "message-square-text",
  texture: "grid-3x3",
  mesh: "boxes",
  pipeline: "workflow",
  capture: "camera",
  debugMessages: "bug",
  diagnosticLog: "file-text",
  comments: "message-square-text",
  performanceCounters: "gauge",
  statistics: "chart-line",
  timeline: "chart-no-axes-gantt",
  python: "square-terminal",
  resourceInspector: "database",
  shader: "code-xml",
  buffer: "rows-3",
  pixelHistory: "rotate-ccw",
  descriptors: "list",
  shaderMessages: "message-square-warning",
  liveCapture: "radio-tower",
  textureList: "images",
  textureInputs: "log-in",
  textureOutputs: "log-out",
  pixelContext: "scan-eye",
  resourceList: "database",
  relatedResources: "network",
  resourceInitialisation: "database-zap",
  resourceUsage: "chart-line",
  preview: "eye",
  meshInput: "log-in",
  meshOutput: "log-out",
  sourceEditor: "file-code",
  projectExplorer: "folder-tree",
  interactiveConsole: "terminal",
  output: "square-arrow-out-up-right",
  help: "circle-question-mark",
  find: "search",
  findResults: "list-filter",
  disassembly: "binary",
  errors: "circle-alert",
  compilation: "hammer",
  watch: "eye",
  variables: "variable",
  constantsResources: "sigma",
  accessedResources: "database",
  callstack: "layers",
  inputSignature: "log-in",
  outputSignature: "log-out",
  fileList: "files",
  debugLog: "bug",
};

const outputDir = resolve(here, "..", "lucide");
mkdirSync(outputDir, { recursive: true });

const escapeAttribute = (value) =>
  String(value)
    .replaceAll("&", "&amp;")
    .replaceAll('"', "&quot;")
    .replaceAll("<", "&lt;");

const serializeNode = ([tag, attributes]) => {
  const attrs = Object.entries(attributes)
    .map(([name, value]) => `${name}="${escapeAttribute(value)}"`)
    .join(" ");
  return `  <${tag}${attrs ? ` ${attrs}` : ""}/>`;
};

const writeFileIfChanged = (path, contents) => {
  try {
    if (readFileSync(path, "utf8") === contents) return false;
  } catch (error) {
    if (error.code !== "ENOENT") throw error;
  }

  writeFileSync(path, contents, "utf8");
  return true;
};

const referencedSources = new Set();
for (const map of [legacy, settings, eventBrowser, panels]) {
  for (const value of Object.values(map)) {
    if (typeof value === "string") referencedSources.add(value);
  }
}

let writtenFiles = 0;
for (const sourceName of [...referencedSources].sort()) {
  const sourceModule = pathToFileURL(
    join(moduleRoot, "lucide", "dist", "esm", "icons", `${sourceName}.mjs`),
  ).href;
  const nodes = (await import(sourceModule)).default;
  const svg =
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" ' +
    'stroke="#27313B" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" ' +
    'shape-rendering="geometricPrecision">\n' +
    `${nodes.map(serializeNode).join("\n")}\n` +
    "</svg>\n";
  writtenFiles += Number(writeFileIfChanged(join(outputDir, `${sourceName}.svg`), svg));
}

const manifest = {
  schema: 1,
  library: {
    name: "Lucide",
    version: lucidePackage.version,
    license: "ISC and MIT (Feather-derived icons)",
    consumedThrough: "guillermolg00/morphicons pinned asset workspace",
  },
  rendering: {
    source: "scalable SVG",
    viewBox: "0 0 24 24",
    strokeWidth: 2,
    edgePolicy:
      "Render at the target monitor DPR; keep source round caps and joins; do not alpha-threshold edges",
  },
  legacy,
  settings,
  eventBrowser,
  panels,
};
writtenFiles += Number(
  writeFileIfChanged(join(outputDir, "manifest.json"), `${JSON.stringify(manifest, null, 2)}\n`),
);

console.log(
  `verified ${referencedSources.size} Lucide UI icons in ${outputDir}; wrote ${writtenFiles} changed files`,
);
