# Basic Rotctld Web GUI
Mark Jessop 2018-07-07

This repository contains a very basic rotctld control web interface, targeted for use on a mobile browser.
I wrote this out of a need to have an easy way to test a new az/el rotator while on a roof, with the controller down in my radio shack.

It is in no way polished, and likely has some interesting bugs (particulatly if multiple clients are connected). Take caution when using it to control expensive antenna arrays!!!


## Dependencies
* Python (3.x)
* Python Modules: flask, flask-socketio  (can obtain using pip)

## Configuration file

Uses a configuration file to specify rotors to connect to. Example:

```
[ROTOR1]
rotctld_port=4533

[ROTOR2]
rotctld_port=4535

[ROTOR3]
rotctld_port=4537
```

Tries by default to look it up in `/usr/local/etc/rotors.conf`, should otherwise
be specified by argument `--config-file=PATH`. See `--help`.

Uses the same configuration file format as the system
specified in https://www.la1k.no/2017/09/15/unified-software-rotor-control-over-the-local-network/, https://github.com/la1k/rotorconfig.

## Usage:
* Start rotctld (refer rotctld documentation)
* `python rotatorgui.py`
* Navigate to http://localhost:5001/   (or equivalent IP)

Run `python rotatorgui.py --help` for command line options:
