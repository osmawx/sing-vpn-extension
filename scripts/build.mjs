import { cp, mkdtemp, readFile, rename, rm, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { transform } from 'esbuild';
import { minify } from 'html-minifier-terser';

const PROJECT_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const SOURCE_DIR = path.join(PROJECT_DIR, 'src', 'extension');
const BUILD_DIR = path.join(PROJECT_DIR, 'build');
const JAVASCRIPT_FILES = ['background.js', 'popup.js', 'proxy-links.js'];

/** Создаёт готовое расширение из исходных файлов. */
async function buildExtension() {
  const stagingDirectory = await mkdtemp(path.join(PROJECT_DIR, '.build-'));
  try {
    await cp(path.join(SOURCE_DIR, 'icons'), path.join(stagingDirectory, 'icons'), { recursive: true });

    for (const filename of JAVASCRIPT_FILES) {
      const source = await readFile(path.join(SOURCE_DIR, filename), 'utf8');
      const result = await transform(source, {
        loader: 'js',
        format: 'esm',
        minify: true,
        legalComments: 'none',
        target: 'chrome108',
      });
      await writeFile(path.join(stagingDirectory, filename), result.code);
    }

    const stylesheet = await readFile(path.join(SOURCE_DIR, 'popup.css'), 'utf8');
    const minifiedStylesheet = await transform(stylesheet, {
      loader: 'css',
      minify: true,
      legalComments: 'none',
      target: 'chrome108',
    });
    await writeFile(path.join(stagingDirectory, 'popup.css'), minifiedStylesheet.code);

    const markup = await readFile(path.join(SOURCE_DIR, 'popup.html'), 'utf8');
    const minifiedMarkup = await minify(markup, {
      collapseWhitespace: true,
      removeComments: true,
      removeRedundantAttributes: true,
    });
    await writeFile(path.join(stagingDirectory, 'popup.html'), `${minifiedMarkup}\n`);

    const manifest = JSON.parse(await readFile(path.join(SOURCE_DIR, 'manifest.json'), 'utf8'));
    await writeFile(path.join(stagingDirectory, 'manifest.json'), `${JSON.stringify(manifest)}\n`);

    // Заменяем работающую сборку только после успешной обработки всех файлов.
    await rm(BUILD_DIR, { recursive: true, force: true });
    await rename(stagingDirectory, BUILD_DIR);
  } finally {
    await rm(stagingDirectory, { recursive: true, force: true });
  }
}

await buildExtension();
