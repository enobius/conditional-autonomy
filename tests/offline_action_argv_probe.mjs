// Run only with independently acquired, pinned upstream source and SDK.
// Usage: node tests/offline_action_argv_probe.mjs <parse-sdk-options.ts> <sdk.mjs>
import { mkdtempSync, readFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { pathToFileURL, fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';

const [parserPath, sdkPath] = process.argv.slice(2);
if (!parserPath || !sdkPath) throw new Error('pinned parser and SDK paths required');
const { parseSdkOptions } = await import(pathToFileURL(resolve(parserPath)).href);
const { query } = await import(pathToFileURL(resolve(sdkPath)).href);
const schema = '{"type":"object"}';
const recorder = fileURLToPath(new URL('./fixtures/claude_argv_recorder.js', import.meta.url));
const output = join(mkdtempSync(join(tmpdir(), 'claude-argv-')), 'argv.json');
const parsed = parseSdkOptions({
  claudeArgs: `--tools= --json-schema '${schema}'`,
  pathToClaudeCodeExecutable: recorder,
}).sdkOptions;
parsed.env = { PATH: process.env.PATH, SYSTEMROOT: process.env.SYSTEMROOT,
  ARG_RECORD_PATH: output };
try {
  for await (const _message of query({ prompt: 'offline test', options: parsed })) {}
} catch (error) {
  // Recorder exits nonzero deliberately; missing output below still fails.
  if (error.exitCode !== 1) throw error;
}
const argv = JSON.parse(readFileSync(output, 'utf8'));
assert.equal(parsed.extraArgs['tools='], null);
assert.equal(parsed.extraArgs['json-schema'], schema);
assert.equal(argv.filter((arg) => arg === '--tools=').length, 1);
const index = argv.indexOf('--json-schema');
assert.ok(index >= 0);
assert.equal(argv[index + 1], schema);
console.log('PASS: pinned parser and SDK delivered --tools= and intact JSON schema');
