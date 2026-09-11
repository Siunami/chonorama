import { createHash } from "node:crypto";
import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = dirname(fileURLToPath(import.meta.url));
const args = process.argv.slice(2);
let destination = join(root, "dist");
if (args[0] === "--out") {
  if (!args[1]) throw new Error("--out requires a destination directory");
  destination = resolve(args[1]);
  args.splice(0, 2);
}
const libraries = args.length ? args : ["shanghai-bund__gpt25aligned"];
if (destination === root) throw new Error("Build destination must not be the source directory");
const viewer = await readFile(join(root, "viewer.html"), "utf8");
const { headers } = JSON.parse(await readFile(join(root, "../vercel.json"), "utf8"));

// Validate and read all source files before replacing a previous build.
const batches = [];
for (const library of libraries) {
  if (!/^[a-z0-9_-]+$/.test(library)) throw new Error(`Invalid library: ${library}`);
  const source = join(root, "output", library);
  const manifest = JSON.parse(await readFile(join(source, "manifest.json"), "utf8"));
  if (!Array.isArray(manifest.years) || !manifest.years.length ||
      !manifest.years.every(Number.isInteger) ||
      new Set(manifest.years).size !== manifest.years.length) {
    throw new Error(`Invalid years in ${library}/manifest.json`);
  }
  const files = [];
  const images = {};
  for (const year of manifest.years) {
    const data = await readFile(join(source, `${year}.jpg`));
    const hash = createHash("sha256").update(data).digest("hex").slice(0, 12);
    const name = `${year}.${hash}.jpg`;
    images[year] = name;
    files.push({ name, data });
  }
  batches.push({ library, manifest: { ...manifest, images }, files });
}

await mkdir(destination, { recursive: true });
await rm(join(destination, "output"), { recursive: true, force: true });
await writeFile(join(destination, "index.html"), viewer.replace(
  /const loc  = .*;/,
  `const loc  = new URLSearchParams(location.search).get("loc") || ${JSON.stringify(libraries[0])};`
));
await writeFile(join(destination, "vercel.json"), JSON.stringify({ headers }, null, 2) + "\n");
for (const { library, manifest, files } of batches) {
  const target = join(destination, "output", library);
  await mkdir(target, { recursive: true });
  await writeFile(join(target, "manifest.json"), JSON.stringify(manifest, null, 2) + "\n");
  for (const { name, data } of files) await writeFile(join(target, name), data);
  console.log(`Built ${library}: ${files.length} panoramas`);
}
console.log(`Site ready in ${destination}`);
