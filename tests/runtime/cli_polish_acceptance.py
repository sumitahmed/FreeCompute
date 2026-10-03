"""Installed-wheel Windows ConPTY and web/image fixtures. No remote GPU use.

Optional test-runner dependencies: pywinpty and pyte (not product dependencies).
First run cli_release_acceptance.py, then pass its output directory here.
"""
import argparse
import http.server
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time

from cli_fixture import Handler, TOKEN, configuration, start_fixture

IMAGE_KEY = 'SYNTHETIC_IMAGE_GATEWAY_CREDENTIAL'


class ResearchHandler(Handler):
    def do_GET(self):
        if self.path in {'/web/search', '/web/page'}:
            self.server.web_reads.append(self.path)
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.end_headers()
            body = (b'<a class="result__a" href="https://example.org/page">Fixture title</a>'
                    b'<a class="result__snippet">Fixture snippet</a>' if self.path.endswith('search')
                    else b'<h1>Fixture page</h1><p>Actual HTTP fixture content.</p><script>omit_me()</script>')
            self.wfile.write(body)
        else:
            super().do_GET()

    def do_POST(self):
        # Preserve the original coding fixture for unrelated requests.
        if not self.authorized():
            return
        request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        self.server.requests.append(request)
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.end_headers()
        tools = [json.loads(m['content']) for m in request['messages'] if m['role'] == 'tool']
        prompt = next(m['content'] for m in reversed(request['messages']) if m['role'] == 'user')
        self.event({'reasoning_content': 'HIDDEN_FIXTURE_REASONING'})
        if 'research fixture' in prompt:
            if len(tools) < 2:
                name, args = ('search_web', {'query': 'fixture search'}) if not tools else ('fetch_url', {'url': 'https://example.org/page'})
                self.event({'tool_calls': [{'index': 0, 'id': 'web-' + str(len(tools)), 'type': 'function',
                            'function': {'name': name, 'arguments': json.dumps(args)}}]}, 'tool_calls')
            else:
                assert tools[0]['results'][0]['title'] == 'Fixture title', tools
                assert 'Actual HTTP fixture content' in tools[1]['content'] and 'omit_me' not in tools[1]['content']
                self.event({'content': 'INSTALLED RESEARCH COMPLETE: both actual HTTP tool results returned.'}, 'stop')
        else:
            for value in ('# Assistant\n\n', 'STREAM_FIRST **bold**\n\n', '```python\nprint("fixture")\n```\n', 'STREAM_LAST'):
                self.event({'content': value})
                self.server.first_chunk.set()
                if 'STREAM_FIRST' in value and self.server.hold_stream:
                    self.server.release.wait(15)
                time.sleep(.12)
            self.event({}, 'stop')
        self.wfile.write(b'data: [DONE]\n\n')
        self.wfile.flush()
        self.server.completed.set()


class ImageHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def authorized(self):
        ok = self.headers.get('Authorization') == 'Bearer ' + IMAGE_KEY
        self.server.probes.append((self.path, ok))
        if not ok:
            self.send_response(401)
            self.end_headers()
        return ok

    def do_GET(self):
        if not self.authorized():
            return
        self.send_response(200)
        self.end_headers()
        if self.path.startswith('/view'):
            self.wfile.write(b'explicit fixture image bytes')
            return
        value = ({'fixture-job': {'outputs': {'9': {'images': [{'filename': 'fixture.png'}]}}}}
                 if self.path.startswith('/history') else
                 {'devices': [{'name': 'fixture image GPU', 'vram_total': 16 * 1024**3, 'vram_free': 8 * 1024**3}],
                  'system': {'ram_total': 32 * 1024**3, 'ram_free': 20 * 1024**3}})
        self.wfile.write(json.dumps(value).encode())

    def do_POST(self):
        if not self.authorized():
            return
        self.server.posts.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"prompt_id":"fixture-job"}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package-dir', type=Path, required=True)
    args = parser.parse_args()
    if os.name != 'nt':
        raise SystemExit('This additional keyboard acceptance uses native Windows ConPTY.')
    import pyte
    from winpty import PtyProcess

    root = args.package_dir.resolve() / ('interactive-' + str(time.time_ns()))
    root.mkdir()  # Never reset a previous workspace or evidence directory.
    workspace = root / 'project with spaces'; workspace.mkdir()
    custom = workspace / 'skills' / 'custom'; custom.mkdir(parents=True)
    (custom / 'SKILL.md').write_text('---\nname: Custom fixture\nslash_command: /custom\ndescription: Actual project fixture skill\nallowed_tools: [read_file]\n---\nRead only.\n', encoding='utf-8')
    scripts = args.package_dir.resolve() / 'installed' / 'Scripts'
    python, executable = scripts / 'python.exe', scripts / 'freecompute.exe'
    assert executable.is_file()
    env = {k: v for k, v in os.environ.items() if not k.startswith(('FREECOMPUTE_', 'HARNESS_', 'RELAYFORGE_')) and k not in {'PYTHONPATH', 'NO_COLOR', 'TERM'}}
    env.update(LOCALAPPDATA=str(root / 'state'), PYTHONIOENCODING='utf-8', PYTHONDONTWRITEBYTECODE='1',
               FC_FIXTURE_KEY=TOKEN, FC_IMAGE_FIXTURE_KEY=IMAGE_KEY, TERM='xterm-256color')
    text, text_thread = start_fixture(str(python))
    # Swap the request handler before any client connects.
    text.RequestHandlerClass = ResearchHandler; text.web_reads = []
    fresh, fresh_thread = start_fixture(str(python))
    fresh.RequestHandlerClass = ResearchHandler; fresh.web_reads = []
    images = []
    for _ in range(2):
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), ImageHandler)
        server.daemon_threads = True
        server.probes, server.posts = [], []
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        images.append((server, thread))
    text_url = f'http://127.0.0.1:{text.server_port}'
    fresh_url = f'http://127.0.0.1:{fresh.server_port}'
    image_url = f'http://127.0.0.1:{images[0][0].server_port}'
    fresh_image_url = f'http://127.0.0.1:{images[1][0].server_port}'
    data = configuration(workspace, text_url)
    data['model_profiles'].append({'profile_id': 'image', 'model': 'ComfyUI-default', 'engine': 'ComfyUI', 'capabilities': ['image_gen'], 'verification': 'fixture-tested'})
    data['workers'].append({'worker_id': 'image-worker', 'location': 'local', 'engine': 'ComfyUI', 'url': image_url,
                            'api_key_env': 'FC_IMAGE_FIXTURE_KEY', 'profiles': ['image'], 'resource_pool': 'separate-fixture', 'resources': ['slot']})
    config = root / 'config.yaml'; config.write_text(json.dumps(data), encoding='utf-8')
    original_config = config.read_bytes()
    checks, snapshots, chunks = [], [], []
    screen = pyte.HistoryScreen(120, 40, history=1000)
    stream = pyte.Stream(screen)
    lock = threading.Lock()
    proc = None

    def record(name, **evidence):
        checks.append({'case': name, 'result': 'passed', **evidence})
        print('PASS ' + name, flush=True)

    def display():
        with lock:
            return '\n'.join(screen.display)

    def capture(name):
        value = display()
        assert not re.search(r'\[(?:0|3[0-7]|9[0-7])m', value), value
        assert TOKEN not in value and IMAGE_KEY not in value and 'HIDDEN_FIXTURE_REASONING' not in value
        snapshots.append({'case': name, 'screen': value})
        return value

    def wait(predicate, label, timeout=12):
        until = time.monotonic() + timeout
        while time.monotonic() < until:
            if predicate():
                return
            time.sleep(.05)
        raise AssertionError(label + '\n' + display())

    def output_after(offset):
        with lock:
            return ''.join(chunks)[offset:]

    def command(value, marker, timeout=12):
        with lock:
            offset = len(''.join(chunks))
        proc.write(value + '\r')
        wait(lambda: marker in output_after(offset), marker, timeout)
        time.sleep(.3)
        capture(value)

    def read_terminal():
        try:
            while True:
                value = proc.read(16384)
                with lock:
                    chunks.append(value); stream.feed(value)
        except EOFError:
            pass

    try:
        powershell = os.path.join(os.environ['SYSTEMROOT'], 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe')
        launch = [powershell, '-NoLogo', '-NoProfile', '-Command', f"& '{executable}' --config '{config}'; exit $LASTEXITCODE"]
        proc = PtyProcess.spawn(launch, cwd=str(workspace), env=env, dimensions=(40, 120), backend='0')
        reader = threading.Thread(target=read_terminal, daemon=True); reader.start()
        wait(lambda: 'freecompute>' in display(), 'installed interactive prompt')
        capture('PowerShell launch')
        proc.write('/')
        wait(lambda: '/help' in display() and 'Show' in display(), 'immediate slash palette')
        capture('slash palette with descriptions')
        proc.write('mo')
        wait(lambda: '/model' in display() and '/models' in display() and '/help' not in display(), 'filtered /mo palette')
        proc.write('\x1b[B\r')
        wait(lambda: 'freecompute> /model' in display(), 'arrow and Enter selection')
        proc.write('\r')
        wait(lambda: 'Choose>' in display() and 'fixture-code' in display() and 'code_tools' in display(), 'actual model selector')
        capture('model selector from installed registry')
        proc.write('\x1b[B\r\r')
        wait(lambda: 'Route selected for new tasks' in ''.join(chunks), 'selected model')
        proc.write('/cu')
        wait(lambda: '/custom' in display() and 'Actual project fixture skill' in display(), 'custom skill completion')
        capture('custom project skill')
        proc.write('\x1b')
        wait(lambda: 'Actual project fixture skill' not in display(), 'Escape dismisses completion')
        proc.write('\x15')
        command('/skills', '/leetcode')
        record('installed PowerShell ConPTY palette/filter/arrows/Enter/Escape and bundled/project skills')
        command('/model chat', 'Route selected for new tasks')
        command('/model co\t', 'Route selected for new tasks')
        capture('Tab autocomplete')
        proc.setwinsize(32, 90)
        screen.resize(lines=32, columns=90)
        proc.write('/im')
        wait(lambda: '/image-model' in display(), 'resized palette')
        capture('90 column terminal resize')
        proc.write('\x1b\x15')
        command('/image-model', 'Choose>')
        wait(lambda: 'configured image workflow' in display(), 'image-only selector')
        capture('image selector')
        proc.write('\x1b[B\r\r')
        wait(lambda: 'Image route:' in ''.join(chunks), 'image selected')
        record('installed text/image selectors, fast Tab and terminal resize')
        command('/connect ' + fresh_url, 'Endpoint changed for this run only')
        command('/connect-image ' + fresh_image_url, 'endpoint changed for this run only')
        assert all(ok for _, ok in images[1][0].probes), images[1][0].probes
        assert config.read_bytes() == original_config
        # Rich rendering is checked while the fixture deliberately holds completion.
        fresh.hold_stream = True
        proc.write('markdown fixture\x1b\rsecond line\r')
        wait(lambda: 'STREAM_FIRST' in display(), 'visible Markdown before fixture completion')
        assert not fresh.completed.is_set()
        capture('streamed Markdown before completion')
        assert fresh.requests[-1]['messages'][-1]['content'].endswith('\nsecond line')
        fresh.release.set()
        wait(lambda: 'STREAM_LAST' in display() and 'Task completed' in display(), 'stream complete')
        capture('completed Markdown/code rendering')
        command('/status', 'Weekly quota')
        command('/image fixture picture', 'Image saved', timeout=18)
        assert len(images[1][0].posts) == 1 and not images[0][0].posts
        assert len(fresh.requests) == 1 and len(text.requests) == 0
        assert all(ok for _, ok in images[1][0].probes)
        record('installed independent authenticated reconnect/image artifact and live Markdown/multiline; no secret/ANSI fragments')
        proc.write('\x1b[A')
        wait(lambda: 'freecompute> /image fixture picture' in display(), 'Up arrow history')
        capture('command history')
        proc.write('\x03')
        time.sleep(.4)
        assert proc.isalive(), 'Ctrl+C at prompt should return to the prompt'
        proc.write('/exit\r')
        wait(lambda: not proc.isalive(), 'interactive exit')
        record('installed prompt history and native Ctrl+C remain usable')

        # Run the actual installed CLI with an explicit test-only web transport.
        # Public URL checks remain covered by the production unit tests; fixture
        # responses come from real HTTP and go through parsing, ToolBroker and SSE.
        bootstrap = root / 'installed_web_check.py'
        bootstrap.write_text('import sys, urllib.request\nfrom harness.tools import web\n'
            'from harness.cli.main import main\n'
            f'base={text_url!r}\n'
            'def fixture_open(request, timeout):\n'
            '    path="/web/search" if "duckduckgo" in request.full_url else "/web/page"\n'
            '    return urllib.request.urlopen(base+path, timeout=timeout)\n'
            'web._open=fixture_open\n'
            f'sys.argv=["freecompute","--config",{str(config)!r}]\n'
            'raise SystemExit(main())\n', encoding='utf-8')
        child = subprocess.run([str(python), str(bootstrap)], cwd=workspace, env=dict(env, NO_COLOR='1'),
                               input='/research research fixture\n/exit\n', text=True, encoding='utf-8', capture_output=True, timeout=35)
        output = child.stdout + child.stderr
        assert child.returncode == 0 and 'INSTALLED RESEARCH COMPLETE' in output, output
        assert 'Searching web' in output and 'Fetching' in output and '/page' in output, output
        assert text.web_reads == ['/web/search', '/web/page'] and len(text.requests) == 3
        assert TOKEN not in output and IMAGE_KEY not in output and 'HIDDEN_FIXTURE_REASONING' not in output
        (root / 'web-transcript.txt').write_text(output, encoding='utf-8')
        record('installed /research makes actual HTTP search/fetch, displays activity and returns results through three model turns')
    finally:
        fresh.release.set()
        if proc and proc.isalive():
            proc.terminate(force=True)
        for server, thread in [(text, text_thread), (fresh, fresh_thread), *images]:
            server.shutdown(); server.server_close(); thread.join(3)
        (root / 'screens.json').write_text(json.dumps(snapshots, indent=2), encoding='utf-8')
        raw = ''.join(chunks)
        assert TOKEN not in raw and IMAGE_KEY not in raw and 'HIDDEN_FIXTURE_REASONING' not in raw
        (root / 'conpty-transcript.txt').write_text(raw, encoding='utf-8')
    (root / 'acceptance.json').write_text(json.dumps({'mode': 'Windows PowerShell in native ConPTY; installed wheel; no GPU', 'checks': checks}, indent=2), encoding='utf-8')
    print(f'PASS {len(checks)} interactive/package extension checks. Evidence: {root}', flush=True)


if __name__ == '__main__':
    main()
