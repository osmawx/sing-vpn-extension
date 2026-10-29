import assert from 'node:assert/strict';
import { readFile, stat } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { test } from 'node:test';

const PROJECT_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

/** Читает файл исходников или сборки. */
async function readProjectFile(directory, filename) {
  return readFile(path.join(PROJECT_DIR, directory, filename), 'utf8');
}

test('build contains valid minified extension assets', async () => {
  const manifest = JSON.parse(await readProjectFile('build', 'manifest.json'));
  assert.equal(manifest.background.service_worker, 'background.js');

  for (const filename of ['background.js', 'popup.js', 'proxy-links.js', 'popup.css', 'popup.html']) {
    const source = await readProjectFile('src/extension', filename);
    const built = await readProjectFile('build', filename);
    assert.ok(built.length < source.length, `${filename} should be smaller`);
    assert.ok(!built.includes('/**'), `${filename} should not contain JSDoc`);
  }

  const markup = await readProjectFile('build', 'popup.html');
  assert.match(markup, /src="popup\.js"/);
  assert.match(markup, /href="popup\.css"/);
  for (const filename of ['16.png', '32.png', '48.png', '128.png']) {
    assert.ok((await stat(path.join(PROJECT_DIR, 'build', 'icons', filename))).size > 0);
  }
});
