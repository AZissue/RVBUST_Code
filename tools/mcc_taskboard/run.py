"""Start the local MCC evaluation and Agent task board."""
from pathlib import Path
import argparse

from evaluation import EvaluationRunner
from seed import seed_tasks
from server import create_server
from store import TaskStore


def main():
    parser = argparse.ArgumentParser(description='MCC local evaluation and Agent task board')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=7788)
    parser.add_argument('--data-dir', default=str(Path(__file__).resolve().parent / 'data'))
    args = parser.parse_args()
    store = TaskStore(args.data_dir)
    seed_tasks(store)
    server = create_server(store, EvaluationRunner(store), args.host, args.port)
    print(f'MCC 评估与 Agent 任务看板：http://{args.host}:{server.server_port}')
    print(f'任务 API：http://{args.host}:{server.server_port}/api/tasks')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
