import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { cp, mkdir, mkdtemp, readFile, rm, stat, symlink, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
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
  assert.match(markup, /id="update-extension"/);
  assert.match(await readProjectFile('build', 'background.js'), /action:"update"/);
  for (const filename of ['16.png', '32.png', '48.png', '128.png']) {
    assert.ok((await stat(path.join(PROJECT_DIR, 'build', 'icons', filename))).size > 0);
  }
});

test('failed build preserves previous extension', async () => {
  const temporaryProject = await mkdtemp(path.join(tmpdir(), 'sing-vpn-build-test-'));
  try {
    await cp(path.join(PROJECT_DIR, 'src'), path.join(temporaryProject, 'src'), { recursive: true });
    await mkdir(path.join(temporaryProject, 'scripts'));
    await cp(path.join(PROJECT_DIR, 'scripts', 'build.mjs'), path.join(temporaryProject, 'scripts', 'build.mjs'));
    await symlink(path.join(PROJECT_DIR, 'node_modules'), path.join(temporaryProject, 'node_modules'));
    await mkdir(path.join(temporaryProject, 'build'));
    await writeFile(path.join(temporaryProject, 'build', 'marker.txt'), 'previous build');
    await writeFile(path.join(temporaryProject, 'src', 'extension', 'manifest.json'), '{ invalid json');

    const result = spawnSync(process.execPath, ['scripts/build.mjs'], {
      cwd: temporaryProject, encoding: 'utf8', timeout: 10000,
    });

    assert.notEqual(result.status, 0);
    assert.equal(await readFile(path.join(temporaryProject, 'build', 'marker.txt'), 'utf8'), 'previous build');
  } finally {
    await rm(temporaryProject, { recursive: true, force: true });
  }
});
