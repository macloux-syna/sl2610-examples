# Homey Voice on SL2610

An English voice and text controller for Homey Self-Hosted Server, integrated as `sl2610-examples/homey_voice`. It uses the repository's `app_utils.speech` services directly: microphone → Silero VAD → Moonshine on the Torq NPU → local command parser → Homey Web API.

All runtime and setup code belongs to this example or the shared repository utilities. The example works with the `Function_calling` directory absent. It does not load FunctionGemma or require an `ASTRA_REPO` setting.

## Install the Homey container

Run these commands **on the SL2610 board**, as root (or prefix Docker/system commands with `sudo`). If Homey is already running, skip this section and continue to **Setup** instead of creating another container.

### Check Docker on the board

```bash
uname -m
docker version
docker info
docker compose version
```

The board should report `aarch64`, and `docker version` should show a working server. These steps require Docker Engine and the Compose plugin on the board. Astra OOBE uses Yocto Linux; use the Docker support provided by your board image/SDK rather than Ubuntu `apt` installation commands. If Docker is installed but stopped, start its service with `systemctl enable --now docker` when your image provides that unit.

Homey's [official Docker guide](https://support.homey.app/hc/en-us/articles/24010537261980-How-to-install-Homey-Self-Hosted-Server-with-Docker-on-Linux) supports 64-bit Arm Linux and requires at least 1 GB available RAM, 1 GB storage, and a LAN IP. Allow additional memory and storage for the voice app, its models, and Docker images. Keep the board and phone on the same LAN during onboarding.

### Create and start the container

Store Homey data outside the source repository:

```bash
mkdir -p /home/root/homey-shs/data
cd /home/root/homey-shs
cat > homey-shs.yml <<'YAML'
services:
  homey-shs:
    image: ghcr.io/athombv/homey-shs:latest
    container_name: homey-shs
    restart: unless-stopped
    network_mode: host
    privileged: true
    volumes:
      - /home/root/homey-shs/data:/homey/user
YAML

docker compose -f homey-shs.yml up --detach
docker compose -f homey-shs.yml ps
docker compose -f homey-shs.yml logs --follow
```

This follows Homey's host-network and privileged-container configuration. Persistent settings live in `/home/root/homey-shs/data`. Docker images use Docker's own data directory; inspect it with `docker info --format '{{.DockerRootDir}}'` when checking available disk space. Ctrl+C stops following logs while the container continues running.

If Docker works but the Compose plugin is unavailable, use this equivalent command **instead of** the Compose startup:

```bash
docker run --detach \
  --name homey-shs \
  --restart unless-stopped \
  --network host \
  --privileged \
  --volume /home/root/homey-shs/data:/homey/user \
  ghcr.io/athombv/homey-shs:latest
```

### Connect Homey to the voice app

Open the Homey mobile app, add a Homey, and choose **Self-Hosted Server**. Complete onboarding and add devices. Then create the API key described in **Configure Homey** below. With host networking, the voice app on this same board uses `HOMEY_URL=http://127.0.0.1:4859` without additional port mappings.

Return to the repository before the voice setup commands:

```bash
cd /home/root/sl2610-examples
```

### Maintain the container

For the Compose installation:

```bash
cd /home/root/homey-shs
# Download and apply an update.
docker compose -f homey-shs.yml pull
docker compose -f homey-shs.yml up --detach
# Stop Homey; data stays in the bind-mounted directory.
docker compose -f homey-shs.yml stop
# Start it again.
docker compose -f homey-shs.yml start
```

For a consistent backup, stop Homey, copy `/home/root/homey-shs/data` to separate storage, and restart it. Restore that directory while Homey is stopped.

## Setup

From the **sl2610-examples repository root**, use the normal shared environment:

The repository ZIP includes the initialized shared submodule. Run the `git submodule` command below when using a Git checkout; skip it when using the extracted ZIP.

```bash
git submodule update --init --recursive
python3 -m venv .venv --system-site-packages
. .venv/bin/activate
python -m pip install -r requirements.txt
python -m pip install -r homey_voice/requirements.txt
bash setup/install_portaudio.sh
python homey_voice/setup_demo.py
```

Use an Astra image and Torq runtime supported by this repository. The PortAudio script installs the upstream board audio libraries. `setup_demo.py` checks the example's dependencies and downloads the Moonshine artifacts into the shared `models/` directory; the repository's `MODELS` environment override is honored. It does not download a language model. Model downloads need internet access. Physical voice/NPU operation still needs validation on your board alongside Homey.

## Configure Homey

Homey Self-Hosted Server on the same host defaults to `http://127.0.0.1:4859`. Run the voice app on the SL2610 host so it can access the microphone and NPU. For separate-container execution, set an address reachable from that container and configure its hardware access.

Create a Homey API key in the Homey Web App under **Settings → API Keys**, with device read/control and zone read permissions. Keep this key on your board.

```bash
cp homey_voice/homey_voice.env.example homey_voice/homey_voice.env
chmod 600 homey_voice/homey_voice.env
```

Edit the file to set `HOMEY_TOKEN` and, if needed, `HOMEY_URL`. Then load it:

```bash
set -a
. homey_voice/homey_voice.env
set +a
python homey_voice/run_cli.py --list
```

The app reads configuration from environment variables. The file is loaded explicitly by the shell or by systemd. For a remote host, use a correctly configured HTTPS origin; TLS verification is enabled and redirects are rejected.

## Run

From the repository root:

```bash
python homey_voice/run_cli.py --prompt "turn on Desk lamp"
python homey_voice/run_cli.py --voice
python homey_voice/run_cli.py --voice --execute
```

The app runs without a display, desktop, or display server. The default is **preview mode**: planned changes are displayed without writes. Add `--execute` to enable real control. Status commands still read Homey. Like the other repository examples, `run_cli.py` contains the main entrypoint.

You can also launch from the example's own directory:

```bash
cd homey_voice
python run_cli.py --voice
python setup_demo.py
```

The default aliases file is resolved relative to this example, so changing the working directory does not change device aliases. `--aliases /path/to/file.json` overrides it. Copy `aliases.example.json` to `aliases.json`, replace placeholders with IDs from `--list`, and remove unused examples. Alias values can be one ID or an explicit list.

Voice mode starts the microphone automatically and stops with Ctrl+C. Listening is continuous while enabled; there is no wake word or speech output. Select input with `--mic 0` or a device-name substring. List audio devices with `python -c "import sounddevice; print(sounddevice.query_devices())"`. `--moonshine-dir` or `MOONSHINE_DIR` overrides the model directory; all four model/tokenizer artifacts must be present. Run through SSH for interactive use, or use the service below for unattended startup. Terminal mode without `--voice` accepts typed commands; `/list` shows devices and `/exit` quits.

Errors appear immediately alongside transcripts as `Error: ...`. This preserves feedback while native microphone logs suppress standard error. Background audio failures are also surfaced in the terminal or service logs.

## Supported commands

Use exact Homey names, room + device names, or configured aliases:

- `turn on Desk lamp`
- `switch Coffee plug off`
- `set Desk lamp to fifty percent`
- `set Hall thermostat to twenty-one point five degrees`
- `status of Desk lamp`
- `turn off all lights in the living room`
- `play Sonos`
- `pause Sonos`
- `volume up on Sonos`
- `volume down on Sonos`

Lights, sockets, brightness, Celsius thermostat targets, speaker playback/volume, and device status are supported. Device metadata determines supported capabilities, limits, steps, and availability. Duplicate names require room qualification or aliases. Room groups include directly assigned lights, not nested subrooms. A bare “lights” must be an actual device name or alias; “all lights” explicitly selects a group.

Colors, blinds, locks, flows, timers, relative brightness/temperature adjustments, and compound commands are not implemented. The constrained parser accepts documented command forms and common spoken numbers; it is not an open-ended conversational assistant. Homey integrations can still rely on their manufacturers' cloud services even though speech inference runs locally.

Group writes are prevalidated and then sequential. If a write fails, completed devices are listed and remaining writes stop. Calls are not atomic, and a timeout may mean the write reached Homey; it is not retried automatically. A successful response means Homey accepted the request, not verified physical actuation.

## Sonos playback and volume

Pair your Sonos speakers with Homey using the Sonos integration first. Run `python homey_voice/run_cli.py --list` to find their exact names and IDs. Use a device name, room + name, or define an alias such as `"sonos": "YOUR_SONOS_DEVICE_ID"` in `aliases.json`. Commands require a named speaker or alias; they do not guess a default room.

Examples with the `sonos` alias:

```bash
python homey_voice/run_cli.py --prompt "play Sonos"
python homey_voice/run_cli.py --prompt "pause Sonos"
python homey_voice/run_cli.py --prompt "volume up on Sonos"
python homey_voice/run_cli.py --prompt "volume down on Sonos"
```

These preview the action. Add `--execute` to send it to Homey. The same phrases work while listening in voice mode. Alternative forms include `resume Sonos`, `play music on Sonos`, `turn up the volume on Sonos`, `turn Sonos volume down`, `volumeup Sonos`, and `volumedown Sonos`.

Play resumes the speaker's current playback/queue; it does not select a song or music service. Pause pauses that playback. Existing Sonos grouping behavior is controlled by Homey and Sonos.

The app uses the speaker's Homey capabilities: `speaker_playing` for play/pause and `volume_up`/`volume_down` for one native volume step. If a native volume button is unavailable, it adjusts the current `volume_set` slider by five percentage points, rounded to the device's supported step and clamped to its reported limits. A missing/unknown volume level or read-only capability produces a visible error instead of guessing a level. These controls use the existing Homey device permissions and do not require a separate Sonos credential.

Capability references: [Homey volume up](https://raw.githubusercontent.com/athombv/node-homey-lib/master/assets/capability/capabilities/volume_up.json), [volume down](https://raw.githubusercontent.com/athombv/node-homey-lib/master/assets/capability/capabilities/volume_down.json), [volume slider](https://raw.githubusercontent.com/athombv/node-homey-lib/master/assets/capability/capabilities/volume_set.json), and [Homey media capabilities](https://apps.developer.homey.app/the-basics/devices/capabilities).

## Startup service

`homey_voice.service.example` uses the shared repository virtual environment and `homey_voice/homey_voice.env`. Edit the paths/user to match your installation, then:

```bash
sudo cp homey_voice/homey_voice.service.example /etc/systemd/system/homey_voice.service
sudo systemctl daemon-reload
sudo systemctl enable --now homey_voice
journalctl -u homey_voice -f
```

The supplied unit starts in preview mode. Add `--execute` to `ExecStart` after manual verification. Stop it with `sudo systemctl disable --now homey_voice`. For migration from the previous standalone service, disable that old service first to avoid two microphone listeners. No changes to the running Homey server are needed.

When migrating the standalone app, copy its `aliases.json` into this example directory and its environment file to `homey_voice/homey_voice.env`. Keep `HOMEY_TOKEN`, `HOMEY_URL`, and any `MOONSHINE_DIR` override; remove `ASTRA_REPO`. Use the repository's `.venv` and the entrypoints above instead of the old standalone directory.

API references: [Homey Web API](https://api.developer.homey.app/), [device endpoints](https://athombv.github.io/node-homey-api/HomeyAPIV3Local.ManagerDevices.html), [Homey capabilities](https://apps-sdk-v3.developer.homey.app/tutorial-device-capabilities.html), [Self-Hosted ports](https://support.homey.app/hc/en-us/articles/24010537261980-How-to-install-Homey-Self-Hosted-Server-with-Docker-on-Linux).
