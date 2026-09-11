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
const { headers, rewrites } = JSON.parse(await readFile(join(root, "../vercel.json"), "utf8"));

// V1 is a frozen deployment, independent of the current viewer and generation inputs.
const snapshotRoot = join(root, "versions", "v1");
const snapshot = JSON.parse(await readFile(join(snapshotRoot, "snapshot.json"), "utf8"));
const snapshotFiles = [];
for (const [name, expectedHash] of Object.entries(snapshot.files)) {
  if (name.startsWith("/") || name.split("/").includes("..")) throw new Error(`Invalid snapshot path: ${name}`);
  let data = await readFile(join(snapshotRoot, name));
  if (createHash("sha256").update(data).digest("hex") !== expectedHash) {
    throw new Error(`V1 snapshot changed: ${name}`);
  }
  if (name === "index.html") {
    data = Buffer.from(data.toString("utf8").replace("<head>",
      '<head>\n<base href="/v1/">\n<link rel="icon" href="data:,">'));
  }
  snapshotFiles.push({ name, data });
}

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
  let registration;
  if (manifest.registration) {
    if (manifest.registration !== "registration.json") throw new Error("Invalid registration filename");
    const data = await readFile(join(source, manifest.registration));
    registration = JSON.parse(data);
    if (registration.version !== 1 || !Number.isInteger(registration.width) ||
        !Number.isInteger(registration.height) || registration.width < 1 ||
        registration.height < 1 || registration.width > 256 || registration.height > 256 ||
        !(registration.range > 0 && registration.range <= .25)) {
      throw new Error(`Invalid registration in ${library}`);
    }
    files.push({ name: manifest.registration, data });
  }
  for (const year of manifest.years) {
    const data = await readFile(join(source, `${year}.jpg`));
    const digest = createHash("sha256").update(data).digest("hex");
    const hash = digest.slice(0, 12);
    if (registration) {
      const frame = registration.frames?.[year];
      if (frame?.sha256 !== digest || typeof frame?.offsets !== "string" ||
          Buffer.from(frame.offsets, "base64").length !== registration.width * registration.height * 4) {
        throw new Error(`Stale or invalid alignment for ${library}/${year}.jpg; review landmarks and run register.py`);
      }
    }
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
await writeFile(join(destination, "vercel.json"), JSON.stringify({ headers, rewrites }, null, 2) + "\n");
for (const { library, manifest, files } of batches) {
  const target = join(destination, "output", library);
  await mkdir(target, { recursive: true });
  await writeFile(join(target, "manifest.json"), JSON.stringify(manifest, null, 2) + "\n");
  for (const { name, data } of files) await writeFile(join(target, name), data);
  console.log(`Built ${library}: ${manifest.years.length} panoramas`);
}
await rm(join(destination, "v1"), { recursive: true, force: true });
for (const { name, data } of snapshotFiles) {
  const target = join(destination, "v1", name);
  await mkdir(dirname(target), { recursive: true });
  await writeFile(target, data);
}
console.log("Preserved V1: original six-image Pro release at /v1");
console.log(`Site ready in ${destination}`);
