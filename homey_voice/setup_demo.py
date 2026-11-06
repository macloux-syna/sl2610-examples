"""Check this example's requirements and download shared Moonshine artifacts."""
import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def setup_homey_voice(moonshine_models=None):
    from app_utils.demo_utils import run_demo_setup_cli
    from app_utils.paths import MODELS_DIR
    from app_utils.torq_examples.moonshine.setup_demo import download_moonshine

    run_demo_setup_cli(
        lambda: download_moonshine(moonshine_models, base_dir=MODELS_DIR),
        Path(__file__).with_name('requirements.txt'),
        logging.getLogger('homey_voice.setup'),
        version_map={'torq.runtime': '>=2.3.0'},
        demo_name='homey_voice',
    )


if __name__ == '__main__':
    from app_utils.log import add_logging_args, configure_logging

    parser = argparse.ArgumentParser(description='Set up Homey Voice and Moonshine models.')
    parser.add_argument('--moonshine-models', nargs='*', default=None)
    add_logging_args(parser)
    args = parser.parse_args()
    configure_logging(args.logging, args.log_file)
    setup_homey_voice(args.moonshine_models)
