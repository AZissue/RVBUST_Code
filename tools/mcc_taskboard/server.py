"""Loopback-only MCC task-board HTTP service."""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from store import ConflictError, PermissionError


class HttpError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def validate_loopback_host(host):
    if host == 'localhost':
        return
    try:
        if not ipaddress.ip_address(host).is_loopback:
            raise ValueError
    except ValueError:
        raise ValueError(f'仅允许回环地址 127.0.0.1 或 localhost，收到: {host}') from None


class BoardHandler(BaseHTTPRequestHandler):
    store = None
    runner = None
    static_dir = None

    def _json(self, value, status=200):
        payload = json.dumps(value, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(payload)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Connection', 'close')
        self.end_headers()
        self.wfile.write(payload)

    def _check_request(self):
        allowed = {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}
        if self.headers.get('Host', '').lower() not in allowed:
            raise HttpError(403, 'Host 不受信任，仅允许本机回环访问')
        origin = self.headers.get('Origin')
        if origin and origin not in {f'http://127.0.0.1:{self.server.server_port}',
                f'http://localhost:{self.server.server_port}'}:
            raise HttpError(403, '拒绝跨站请求')

    def _body(self):
        content_type = self.headers.get('Content-Type', '').split(';', 1)[0].strip().lower()
        if content_type != 'application/json':
            raise HttpError(415, '写接口仅接受 application/json')
        try:
            length = int(self.headers.get('Content-Length', '0'))
        except ValueError:
            raise HttpError(400, 'Content-Length 无效') from None
        if length < 0:
            raise HttpError(400, 'Content-Length 不能为负数')
        if length > 65536:
            raise HttpError(413, '请求体超过 64KB 限制')
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        value = json.loads(raw.decode('utf-8'))
        if not isinstance(value, dict):
            raise ValueError('JSON 请求体必须是对象')
        return value

    def _route(self):
        return urlsplit(self.path)

    def do_GET(self):
        try:
            self._check_request()
            route = self._route()
            if route.path == '/':
                return self._static('index.html')
            if route.path == '/app.css':
                return self._static('app.css')
            if route.path == '/app.js':
                return self._static('app.js')
            if route.path == '/favicon.ico':
                self.send_response(204)
                self.end_headers()
                return
            if route.path == '/api/summary':
                return self._json(self.store.summary())
            if route.path == '/api/tasks':
                status = parse_qs(route.query).get('status', [''])[0]
                tasks = self.store.all_tasks()
                if status:
                    tasks = [task for task in tasks if task['status'] == status]
                return self._json({'tasks': tasks})
            if route.path.startswith('/api/tasks/'):
                task_id = route.path.rsplit('/', 1)[-1]
                return self._json(self.store.get(task_id))
            if route.path == '/api/evaluation':
                return self._json(self.store.evaluation())
            self._json({'error': 'Not Found'}, 404)
        except HttpError as exc:
            self._json({'error': str(exc)}, exc.status)
        except KeyError as exc:
            self._json({'error': str(exc)}, 404)
        except Exception as exc:
            self._json({'error': str(exc)}, 500)

    def do_POST(self):
        try:
            self._check_request()
            route = self._route()
            data = self._body()
            if route.path == '/api/evaluate':
                if not self.runner.start():
                    return self._json({'error': '评估正在运行'}, 409)
                return self._json({'started': True}, 202)
            parts = route.path.strip('/').split('/')
            if len(parts) == 4 and parts[:2] == ['api', 'tasks']:
                task_id, action = parts[2], parts[3]
                if action == 'claim':
                    return self._json(self.store.claim(task_id, data.get('agent')))
                if action == 'release':
                    return self._json(self.store.release(task_id, data.get('agent')))
                if action == 'status':
                    return self._json(self.store.set_status(
                        task_id, data.get('status'), data.get('agent'), data.get('note', '')))
            self._json({'error': 'Not Found'}, 404)
        except HttpError as exc:
            self._json({'error': str(exc)}, exc.status)
        except json.JSONDecodeError as exc:
            self._json({'error': f'JSON 格式错误: {exc}'}, 400)
        except PermissionError as exc:
            self._json({'error': str(exc)}, 403)
        except ConflictError as exc:
            self._json({'error': str(exc)}, 409)
        except KeyError as exc:
            self._json({'error': str(exc)}, 404)
        except ValueError as exc:
            self._json({'error': str(exc)}, 400)
        except Exception as exc:
            self._json({'error': str(exc)}, 500)

    def _static(self, name):
        path = self.static_dir / name
        if not path.is_file():
            return self._json({'error': 'Not Found'}, 404)
        payload = path.read_bytes()
        content_type = {'index.html': 'text/html; charset=utf-8',
            'app.css': 'text/css; charset=utf-8',
            'app.js': 'application/javascript; charset=utf-8'}[name]
        self.send_response(200)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(payload)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format, *args):
        pass


def create_server(store, runner, host='127.0.0.1', port=7788, static_dir=None):
    validate_loopback_host(host)
    handler = type('BoundBoardHandler', (BoardHandler,), {
        'store': store,
        'runner': runner,
        'static_dir': Path(static_dir or Path(__file__).resolve().parent / 'static'),
    })
    return ThreadingHTTPServer((host, port), handler)
