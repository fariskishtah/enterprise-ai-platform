import { spawnSync } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";

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

const vulnerabilities = Object.entries(report.vulnerabilities ?? {});
const blocking = vulnerabilities.filter(([, finding]) =>
  ["high", "critical"].includes(finding.severity),
);

if (blocking.length > 0) {
  console.error(
    `npm audit found HIGH/CRITICAL packages: ${blocking
      .map(([name]) => name)
      .join(", ")}`,
  );
  process.exit(1);
}

if (audit.status !== 0 && vulnerabilities.length === 0) {
  process.stderr.write(audit.stderr || "npm audit failed without findings.\n");
  process.exit(audit.status ?? 2);
}

console.log("npm audit found no HIGH or CRITICAL vulnerabilities.");
