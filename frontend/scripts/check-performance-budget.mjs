import { readFile, readdir, stat } from "node:fs/promises";

const DIST = new URL("../dist/", import.meta.url);
const MANIFEST = new URL("../dist/.vite/manifest.json", import.meta.url);
const KIB = 1024;
const budgets = {
  initialJavaScript: 400 * KIB,
  individualJavaScript: 500 * KIB,
  loginImage: 300 * KIB,
  totalInitialAssets: 1024 * KIB,
};

const manifest = JSON.parse(await readFile(MANIFEST, "utf8"));
const entries = Object.values(manifest);
const entry = entries.find((item) => item.isEntry === true);

if (entry === undefined) {
  throw new Error("Vite manifest does not contain an application entry.");
}

const bytes = async (relativePath) => (await stat(new URL(relativePath, DIST))).size;
const initialFiles = new Set();
const visit = (item) => {
  initialFiles.add(item.file);
  for (const css of item.css ?? []) initialFiles.add(css);
  for (const asset of item.assets ?? []) initialFiles.add(asset);
  for (const importedKey of item.imports ?? []) visit(manifest[importedKey]);
};
visit(entry);

const initialJavaScriptFiles = [...initialFiles].filter((file) => file.endsWith(".js"));
const initialJavaScript = (
  await Promise.all(initialJavaScriptFiles.map((file) => bytes(file)))
).reduce((total, size) => total + size, 0);
const totalInitialAssets = (
  await Promise.all([...initialFiles].map((file) => bytes(file)))
).reduce((total, size) => total + size, 0);

const assetNames = await readdir(new URL("assets/", DIST));
const javascriptFiles = assetNames.filter((name) => name.endsWith(".js"));
const javascriptSizes = await Promise.all(
  javascriptFiles.map(async (name) => [name, await bytes(`assets/${name}`)]),
);
const oversizedChunks = javascriptSizes.filter(
  ([, size]) => size > budgets.individualJavaScript,
);
const loginImageName = assetNames.find((name) =>
  name.startsWith("fk-login-background"),
);

if (loginImageName === undefined) {
  throw new Error("Optimized login image was not emitted by the production build.");
}
const loginImage = await bytes(`assets/${loginImageName}`);

const failures = [];
if (initialJavaScript > budgets.initialJavaScript) {
  failures.push(
    `initial JavaScript ${initialJavaScript} > ${budgets.initialJavaScript} bytes`,
  );
}
if (totalInitialAssets > budgets.totalInitialAssets) {
  failures.push(
    `initial assets ${totalInitialAssets} > ${budgets.totalInitialAssets} bytes`,
  );
}
if (loginImage > budgets.loginImage) {
  failures.push(`login image ${loginImage} > ${budgets.loginImage} bytes`);
}
for (const [name, size] of oversizedChunks) {
  failures.push(`JavaScript chunk ${name} ${size} > 512000 bytes`);
}

console.log(
  JSON.stringify(
    {
      initialJavaScriptBytes: initialJavaScript,
      largestJavaScriptChunkBytes: Math.max(...javascriptSizes.map(([, size]) => size)),
      loginImageBytes: loginImage,
      totalInitialAssetBytes: totalInitialAssets,
    },
    null,
    2,
  ),
);

if (failures.length > 0) {
  throw new Error(`Release performance budget failed:\n- ${failures.join("\n- ")}`);
}
