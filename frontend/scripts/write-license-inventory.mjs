import { mkdir, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";

const output = resolve(
  process.argv[2] ?? "../artifacts/release/frontend-licenses.json",
);
const lock = JSON.parse(
  await import("node:fs/promises").then(({ readFile }) =>
    readFile(new URL("../package-lock.json", import.meta.url), "utf8"),
  ),
);

const inventory = Object.entries(lock.packages)
  .filter(([path]) => path.startsWith("node_modules/"))
  .map(([path, metadata]) => ({
    development: metadata.dev === true,
    license: metadata.license ?? "UNKNOWN",
    package: path.slice("node_modules/".length),
    version: metadata.version ?? "UNKNOWN",
  }))
  .sort((left, right) => left.package.localeCompare(right.package));

await mkdir(dirname(output), { recursive: true });
await writeFile(output, `${JSON.stringify(inventory, null, 2)}\n`, "utf8");

const unknown = inventory.filter(({ license }) => license === "UNKNOWN");
console.log(`Wrote ${inventory.length} frontend package license records to ${output}.`);
if (unknown.length > 0) {
  console.warn(`${unknown.length} packages require manual license identification.`);
}
