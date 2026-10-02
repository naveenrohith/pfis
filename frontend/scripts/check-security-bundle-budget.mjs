import { gzipSync } from 'node:zlib';
import { readdir, readFile, stat } from 'node:fs/promises';
import { join } from 'node:path';

const assetRoot = new URL('../security-dist/assets/', import.meta.url);
const files = await readdir(assetRoot);
const jsFiles = files.filter((file) => file.endsWith('.js'));
if (jsFiles.length === 0) {
  throw new Error('Security console build contains no JavaScript assets.');
}
const sizes = await Promise.all(
  jsFiles.map(async (file) => {
    const path = new URL(file, assetRoot);
    const [content, metadata] = await Promise.all([readFile(path), stat(path)]);
    return { file, gzipBytes: gzipSync(content).byteLength, bytes: metadata.size };
  }),
);
const initialGzipBytes = sizes.reduce((sum, item) => sum + item.gzipBytes, 0);
const budget = 240 * 1024;
console.log(`Security console JS: ${(initialGzipBytes / 1024).toFixed(1)} KB gzip across ${jsFiles.length} file(s).`);
if (initialGzipBytes > budget) {
  throw new Error(`Security console bundle exceeds the 240 KB gzip budget (${initialGzipBytes} bytes).`);
}
