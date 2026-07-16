import { gzipSync } from 'node:zlib';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { basename, dirname, join, relative, resolve } from 'node:path';

const distDir = resolve(process.cwd(), 'dist');
const indexPath = join(distDir, 'index.html');
const initialBudget = 100 * 1024;
const lazyBudget = 130 * 1024;

const normalizeAsset = (asset) => asset.replace(/^\/dashboard\//, '').replace(/^\//, '');
const indexHtml = readFileSync(indexPath, 'utf8');
const initialEntries = [...indexHtml.matchAll(/<script[^>]+src=["']([^"']+\.js)["']/g)].map(
  ([, asset]) => normalizeAsset(asset),
);

if (initialEntries.length === 0) {
  throw new Error('Bundle budget check could not find the dashboard entry script.');
}

const allJavascript = [];
const visitDirectory = (directory) => {
  for (const entry of readdirSync(directory)) {
    const path = join(directory, entry);
    if (statSync(path).isDirectory()) visitDirectory(path);
    else if (path.endsWith('.js')) allJavascript.push(relative(distDir, path).replaceAll('\\', '/'));
  }
};
visitDirectory(distDir);

const staticImportPattern = /(?:from\s*|import\s*)["']([^"']+\.js)["']/g;
const initialGraph = new Set();
const visitInitial = (asset) => {
  if (initialGraph.has(asset)) return;
  initialGraph.add(asset);
  const source = readFileSync(join(distDir, asset), 'utf8');
  for (const [, imported] of source.matchAll(staticImportPattern)) {
    if (imported.startsWith('.')) {
      visitInitial(relative(distDir, resolve(distDir, dirname(asset), imported)).replaceAll('\\', '/'));
    }
  }
};
initialEntries.forEach(visitInitial);

const gzipBytes = (asset) => gzipSync(readFileSync(join(distDir, asset))).byteLength;
const initialBytes = [...initialGraph].reduce((total, asset) => total + gzipBytes(asset), 0);
const failures = [];

if (initialBytes > initialBudget) {
  failures.push(`Initial route is ${(initialBytes / 1024).toFixed(1)} KB gzip (budget: 100 KB).`);
}

for (const asset of allJavascript.filter((asset) => !initialGraph.has(asset))) {
  const size = gzipBytes(asset);
  if (size > lazyBudget) {
    failures.push(`${basename(asset)} is ${(size / 1024).toFixed(1)} KB gzip (lazy budget: 130 KB).`);
  }
}

console.log(`Initial route: ${(initialBytes / 1024).toFixed(1)} KB gzip across ${initialGraph.size} file(s).`);
console.log(`Lazy chunks checked: ${allJavascript.length - initialGraph.size}.`);

if (failures.length > 0) {
  console.error(failures.join('\n'));
  process.exitCode = 1;
} else {
  console.log('Bundle budgets passed.');
}
