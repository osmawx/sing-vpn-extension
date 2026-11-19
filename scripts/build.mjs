import { cp, mkdtemp, readFile, rename, rm, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { gzipSync } from 'node:zlib';

import CleanCSS from 'clean-css';
import { minify as minifyHtml } from 'html-minifier-terser';
import { minify as minifyJavaScript } from 'terser';

const PROJECT_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const SOURCE_DIR = path.join(PROJECT_DIR, 'src', 'extension');
const BUILD_DIR = path.join(PROJECT_DIR, 'build');
const JAVASCRIPT_FILES = ['background.js', 'popup.js', 'proxy-links.js', 'configuration.js', 'runtime-version.js'];

/** Packages the fixed macOS launcher as a tar.gz with executable permissions. */
function createInstallerArchive(contents) {
  const header = Buffer.alloc(512);
  header.write('Install Sing.command', 0);
  header.write('0000755\0', 100);
  header.write('0000000\0', 108);
  header.write('0000000\0', 116);
  header.write(`${contents.length.toString(8).padStart(11, '0')}\0`, 124);
  header.write('00000000000\0', 136);
  header.fill(32, 148, 156);
  header.write('0', 156);
  header.write('ustar\0', 257);
  header.write('00', 263);
  // Tar checksums treat the checksum field as eight spaces.
  const checksum = header.reduce((sum, byte) => sum + byte, 0);
  header.write(`${checksum.toString(8).padStart(6, '0')}\0 `, 148);
  const padding = Buffer.alloc((512 - contents.length % 512) % 512);
  return gzipSync(Buffer.concat([header, contents, padding, Buffer.alloc(1024)]));
}

/** Создаёт готовое расширение из исходных файлов. */
async function buildExtension() {
  const stagingDirectory = await mkdtemp(path.join(PROJECT_DIR, '.build-'));
  try {
    await cp(path.join(SOURCE_DIR, 'icons'), path.join(stagingDirectory, 'icons'), { recursive: true });
    const installer = await readFile(path.join(PROJECT_DIR, 'src', 'installer', 'Install Sing.command'));
    await writeFile(path.join(stagingDirectory, 'sing-installer.tar.gz'), createInstallerArchive(installer));

    for (const filename of JAVASCRIPT_FILES) {
      const source = await readFile(path.join(SOURCE_DIR, filename), 'utf8');
      const result = await minifyJavaScript(source, {
        module: true,
        ecma: 2022,
        format: { comments: false },
      });
      await writeFile(path.join(stagingDirectory, filename), `${result.code}\n`);
    }

    const stylesheet = await readFile(path.join(SOURCE_DIR, 'popup.css'), 'utf8');
    const minifiedStylesheet = new CleanCSS({ level: { 1: { specialComments: 0 } } }).minify(stylesheet);
    if (minifiedStylesheet.errors.length) {
      throw new Error(minifiedStylesheet.errors.join('\n'));
    }
    await writeFile(path.join(stagingDirectory, 'popup.css'), `${minifiedStylesheet.styles}\n`);

    const markup = await readFile(path.join(SOURCE_DIR, 'popup.html'), 'utf8');
    const minifiedMarkup = await minifyHtml(markup, {
      collapseWhitespace: true,
      removeComments: true,
      removeRedundantAttributes: true,
    });
    await writeFile(path.join(stagingDirectory, 'popup.html'), `${minifiedMarkup}\n`);

    const manifest = JSON.parse(await readFile(path.join(SOURCE_DIR, 'manifest.json'), 'utf8'));
    const packageMetadata = JSON.parse(await readFile(path.join(PROJECT_DIR, 'package.json'), 'utf8'));
    manifest.version = process.env.RELEASE_VERSION || packageMetadata.version;
    await writeFile(path.join(stagingDirectory, 'manifest.json'), `${JSON.stringify(manifest)}\n`);
    await writeFile(path.join(stagingDirectory, 'release-info.json'), `${JSON.stringify({ managed: Boolean(process.env.RELEASE_VERSION) })}\n`);

    // Заменяем работающую сборку только после успешной обработки всех файлов.
    await rm(BUILD_DIR, { recursive: true, force: true });
    await rename(stagingDirectory, BUILD_DIR);
  } finally {
    await rm(stagingDirectory, { recursive: true, force: true });
  }
}

await buildExtension();
