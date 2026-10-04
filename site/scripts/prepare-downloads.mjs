import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const siteRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const repoRoot = resolve(siteRoot, '..');
const git = (args) => execFileSync('git', args, { cwd: repoRoot, maxBuffer: 30 * 1024 * 1024 });
const commit = git(['rev-parse', 'HEAD']).toString().trim();
const version = git(['show', `${commit}:pyproject.toml`]).toString().match(/^version = "([^"]+)"/m)?.[1];
if (!version) throw new Error('Cannot identify the CLI source version.');

const downloads = resolve(siteRoot, 'public/downloads');
mkdirSync(downloads, { recursive: true });
const archiveName = 'freecompute-v1-source.zip';
// Explicit tracked paths exclude private config, runtime state, site assets and .env.
git(['archive', '--format=zip', '--prefix=FreeCompute-v1-preview/',
  `--output=${resolve(downloads, archiveName)}`, commit, '--',
  'harness', 'kaggle', 'skills', 'knowledgebase', 'tests',
  'README.md', 'LICENSE', 'SECURITY.md', 'pyproject.toml', '.gitignore', 'AGENTS.md']);
const notebookName = 'freecompute_dual_gpu_server.ipynb';
const notebook = git(['show', `${commit}:kaggle/${notebookName}`]);
const notebookData = JSON.parse(notebook.toString());
if (notebookData.cells.some((cell) => (cell.outputs?.length ?? 0) > 0)) {
  throw new Error('The notebook contains captured outputs. Inspect before publishing.');
}
writeFileSync(resolve(downloads, notebookName), notebook);

const files = [archiveName, notebookName].map((name) => ({
  name,
  sha256: createHash('sha256').update(readFileSync(resolve(downloads, name))).digest('hex'),
}));
writeFileSync(resolve(downloads, 'SHA256SUMS.txt'), files.map((file) => `${file.sha256}  ${file.name}`).join('\n') + '\n');
const metadata = { version, commit, files };
writeFileSync(resolve(downloads, 'provenance.json'), JSON.stringify(metadata, null, 2) + '\n');
mkdirSync(resolve(siteRoot, 'src/data'), { recursive: true });
writeFileSync(resolve(siteRoot, 'src/data/downloads.json'), JSON.stringify(metadata, null, 2) + '\n');
console.log(`Prepared tracked CLI source preview ${version} (${commit.slice(0, 7)}) and unchanged worker notebook.`);
