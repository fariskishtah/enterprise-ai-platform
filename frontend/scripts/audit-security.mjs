import { spawnSync } from "node:child_process";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";

const EXCEPTION_ID = "SEC-2026-003";
const EXCEPTION_EXPIRES = "2026-08-15";
const RSC_ADVISORY_SOURCE = 1124282;
const outputPath = process.argv[2] ? resolve(process.argv[2]) : null;

const audit = spawnSync("npm", ["audit", "--audit-level=high", "--json"], {
  encoding: "utf8",
  maxBuffer: 16 * 1024 * 1024,
});

let report;
try {
  report = JSON.parse(audit.stdout);
} catch {
  process.stderr.write(audit.stderr || "npm audit did not return valid JSON.\n");
  process.exit(2);
}

if (outputPath) {
  mkdirSync(dirname(outputPath), { recursive: true });
  writeFileSync(outputPath, `${JSON.stringify(report, null, 2)}\n`);
}

const today = new Date().toISOString().slice(0, 10);
if (today > EXCEPTION_EXPIRES) {
  console.error(
    `${EXCEPTION_ID} expired on ${EXCEPTION_EXPIRES}; review the router migration.`,
  );
  process.exit(1);
}

const lock = JSON.parse(readFileSync(new URL("../package-lock.json", import.meta.url)));
const routerVersion = lock.packages?.["node_modules/react-router"]?.version;
const domVersion = lock.packages?.["node_modules/react-router-dom"]?.version;
if (routerVersion !== "7.18.1" || domVersion !== "7.18.1") {
  console.error(
    `${EXCEPTION_ID} applies only to react-router and react-router-dom 7.18.1.`,
  );
  process.exit(1);
}

const vulnerabilities = Object.entries(report.vulnerabilities ?? {});
const blocking = vulnerabilities.filter(([packageName, finding]) => {
  if (!["high", "critical"].includes(finding.severity)) {
    return false;
  }
  if (packageName === "react-router") {
    return !finding.via.every(
      (via) =>
        typeof via === "object" &&
        via.source === RSC_ADVISORY_SOURCE &&
        via.name === "react-router",
    );
  }
  if (packageName === "react-router-dom") {
    return !(
      finding.via.length === 1 &&
      finding.via[0] === "react-router" &&
      report.vulnerabilities?.["react-router"]
    );
  }
  return true;
});

if (blocking.length > 0) {
  console.error(
    `npm audit found unexcepted HIGH/CRITICAL packages: ${blocking
      .map(([name]) => name)
      .join(", ")}`,
  );
  process.exit(1);
}

if (audit.status !== 0 && vulnerabilities.length === 0) {
  process.stderr.write(audit.stderr || "npm audit failed without findings.\n");
  process.exit(audit.status ?? 2);
}

const excepted = vulnerabilities.filter(([, finding]) =>
  ["high", "critical"].includes(finding.severity),
);
console.log(
  excepted.length === 0
    ? "npm audit found no HIGH or CRITICAL vulnerabilities."
    : `npm audit retained ${excepted.length} package finding(s) under ${EXCEPTION_ID}; unfiltered JSON was preserved.`,
);
