#!/usr/bin/env node
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';

const mode = new Set(process.argv.slice(2));
const errors = [];
function walk(dir) {
  for (const entry of readdirSync(dir)) {
    if (['.git', '.gc', 'node_modules', 'build', 'dist'].includes(entry)) continue;
    const p = join(dir, entry);
    const st = statSync(p);
    if (st.isDirectory()) walk(p);
    else check(p);
  }
}
function check(path) {
  const text = readFileSync(path, 'utf8');
  if (!mode.has('--workflows') && /(^|\n)TODO(\b|:)/.test(text)) errors.push(`${path}: TODO marker`);
  if (/-----BEGIN (?:RSA |OPENSSH |EC |DSA |PGP )?PRIVATE KEY-----/.test(text)) errors.push(`${path}: private key marker`);
  if (mode.has('--workflows') && /uses:\s*[^@\s]+\s*$/m.test(text)) errors.push(`${path}: unpinned workflow action`);
}
walk(process.cwd());
if (errors.length) {
  console.error(errors.join('\n'));
  process.exit(1);
}
console.log('docs policy passed');
