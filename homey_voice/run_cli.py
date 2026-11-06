"""Homey voice CLI for the SL2610.

Run from this directory with: python run_cli.py --voice
"""
import argparse
import json
import os
import signal
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import ControlError, Controller, HomeyClient


def main():
    p = argparse.ArgumentParser(description='English voice control for Homey on SL2610')
    p.add_argument('--address', default=os.getenv('HOMEY_URL', 'http://127.0.0.1:4859'))
    p.add_argument('--aliases', default=str(Path(__file__).with_name('aliases.json')))
    p.add_argument('--moonshine-dir', default=os.getenv('MOONSHINE_DIR'))
    p.add_argument('--mic', default=None)
    p.add_argument('--execute', action='store_true', help='Send changes to Homey (default: preview only)')
    mode = p.add_mutually_exclusive_group()
    mode.add_argument('--prompt')
    mode.add_argument('--list', action='store_true')
    mode.add_argument('--voice', action='store_true', help='Headless microphone control')
    args = p.parse_args()
    try:
        aliases = {}
        if os.path.exists(args.aliases):
            with open(args.aliases) as f:
                aliases = json.load(f)
            if not isinstance(aliases, dict):
                raise ControlError('Alias file must contain a JSON object.')
        controller = Controller(HomeyClient(args.address, os.getenv('HOMEY_TOKEN', '')), aliases, not args.execute)
        if args.list:
            print(controller.inventory())
        elif args.prompt:
            print(controller.run(args.prompt))
        elif args.voice:
            from voice import create_voice
            lock = threading.Lock()
            def heard(text):
                with lock:
                    print('Heard:', text, flush=True)
                    try:
                        print(controller.run(text), flush=True)
                    except ControlError as e:
                        # Astra's audio source redirects process-wide stderr to
                        # silence native microphone logs while listening.
                        print(f'Error: {e}', flush=True)
            pipe = create_voice(args.moonshine_dir, args.mic, heard)
            stopping = threading.Event()
            signal.signal(signal.SIGTERM, lambda *_: stopping.set())
            signal.signal(signal.SIGINT, lambda *_: stopping.set())
            pipe.start()
            print('Listening continuously in English. Ctrl+C to stop. '
                  + ('PREVIEW ONLY.' if controller.preview else 'LIVE CONTROL.'), flush=True)
            try:
                while not stopping.wait(0.5):
                    if not pipe.running:
                        raise ControlError(pipe.error or 'Microphone worker stopped.')
            finally:
                pipe.stop()
        else:
            print('English commands; /list shows devices, /exit quits. '
                  + ('PREVIEW ONLY.' if controller.preview else 'LIVE CONTROL.'))
            while True:
                try:
                    text = input('> ').strip()
                except (EOFError, KeyboardInterrupt):
                    break
                if text == '/exit':
                    break
                if not text:
                    continue
                try:
                    print(controller.inventory() if text == '/list' else controller.run(text))
                except ControlError as e:
                    print(e)
    except (ControlError, ValueError, OSError, ImportError) as e:
        print(str(e), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
