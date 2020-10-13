#!/usr/bin/env python3
#
#   ROTCTLD Basic Web GUI
#
#   Copyright (C) 2018  Mark Jessop <vk5qi@rfhead.net>
#   Released under GNU GPL v3 or later
#
import json
import flask
from flask_socketio import SocketIO, emit
from flask import request
import time
import socket
import sys
import datetime
import logging


# Define Flask Application, and allow automatic reloading of templates for dev
app = flask.Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.jinja_env.auto_reload = True

# SocketIO instance
socketio = SocketIO(app)

current_setpoints = {}
current_positions = {}

class ROTCTLD(object):
    """ rotctld (hamlib) communication class """
    # Note: This is a massive hack.

    def __init__(self, hostname, port=4533, poll_rate=5, timeout=5, az_180 = False):
        """ Open a connection to rotctld, and test it for validity """
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(timeout)

        self.hostname = hostname
        self.port = port


    def connect(self):
        """ Connect to rotctld instance """
        self.sock.connect((self.hostname,self.port))
        model = self.get_model()
        if model == None:
            # Timeout!
            self.close()
            raise Exception("Timeout!")
        else:
            return model


    def close(self):
        self.sock.close()


    def send_command(self, command):
        """ Send a command to the connected rotctld instance,
            and return the return value.
        """
        self.sock.sendall((command+'\n').encode())
        try:
            recv_msg = self.sock.recv(1024).decode()
        except:
            recv_msg = None

        return recv_msg


    def get_model(self):
        """ Get the rotator model from rotctld """
        model = self.send_command('_')
        return model


    def set_azel(self,azimuth,elevation):
        """ Command rotator to a particular azimuth/elevation """
        # Sanity check inputs.
        if elevation > 90.0:
            elevation = 90.0
        elif elevation < 0.0:
            elevation = 0.0

        if azimuth > 360.0:
            azimuth = azimuth % 360.0


        command = "P %3.1f %2.1f" % (azimuth,elevation)
        response = self.send_command(command)
        if "RPRT 0" in response:
            return True
        else:
            return False


    def get_azel(self):
        """ Poll rotctld for azimuth and elevation """
        # Send poll command and read in response.
        response = self.send_command('p')

        # Attempt to split response by \n (az and el are on separate lines)
        try:
            lines = response.split('\n')
            az = float(lines[0])
            el = float(lines[1])
            return (az, el)
        except:
            logging.error("Could not parse position: %s" % response)
            return (None,None)


    def halt(self):
        """ Immediately halt rotator movement, if it support it """
        self.send_command('S')


def limit(num, minimum, maximum):
    """Limits input 'num' between minimum and maximum values."""
    return max(min(num, maximum), minimum)


# Rotator map.
rotators = {}

# Map over rotator resolutions.
increments = {}

#
#   Flask Routes
#

@app.route("/")
def flask_index():
    """ Render main index page """
    rotator_names = list(rotators)
    return flask.render_template('index.html', chosen_rotor_name=rotator_names[0], rotor_increment=increments[rotator_names[0]], rotator_names=rotator_names)


@app.route("/<rotorname>")
def flask_show_rotor(rotorname):
    rotator_names = list(rotators)
    if rotorname not in rotator_names:
        return flask.render_template('404.html')

    rotor_increment = increments[rotorname]

    return flask.render_template('index.html', chosen_rotor_name=rotorname, rotor_increment=rotor_increment, rotator_names=rotator_names)


#
# SocketIO Handlers
#

@socketio.on('client_connected', namespace='/update_status')
def client_connected(data):
    #display current position
    read_position(data)
    #and setpoint
    emit('setpoint_event', current_setpoints[data['rotator_key']])


@socketio.on('update_setpoint', namespace='/update_status')
def update_setpoint(data):
    rotator = data['rotator_key']
    motor = data['motor']

    setpoint = current_setpoints[rotator]
    position = current_positions[rotator]

    #set new setpoints
    if 'delta' in data:
        setpoint[motor] = position[motor] + data['delta']
    else:
        try:
            setpoint[motor] = float(data['val'])
        except ValueError:
            # bogus input, just ignore it and quit
            return

    #limit azi and ele to 0-360 and 0-180 for setpoint display purposes,
    #though rotctld will take care of this automatically
    az = setpoint['azimuth'] = setpoint['azimuth'] % 360
    el = setpoint['elevation'] = limit(setpoint['elevation'], 0, 180.0)

    #set rotctld to current setpoint
    rotators[rotator].set_azel(az, el)

    #update client display
    emit('setpoint_event', setpoint)


@socketio.on('halt_rotator', namespace='/update_status')
def halt_rotator(data):
    rotator = data['rotator_key']
    rotators[rotator].halt()

    #update setpoint to current position
    (az, el) = rotators[rotator].get_azel()
    current_setpoints[rotator] = {'azimuth': az, 'elevation': el}
    emit('setpoint_event', current_setpoints[rotator])


@socketio.on('get_position', namespace='/update_status')
def read_position(data):
    rotator = data['rotator_key']
    position = current_positions[rotator]

    (az, el) = rotators[rotator].get_azel()
    if (az == None):
        return
    else:
        position = {'azimuth': az, 'elevation': el}

        #display current position
        emit('position_event', position)


if __name__ == "__main__":
    import argparse
    from configparser import ConfigParser

    parser = argparse.ArgumentParser()
    parser.add_argument("-l", "--listen_port",default=5001,help="Port to run Web Server on. (Default: 5001)")
    parser.add_argument("--config-file", default='/usr/local/etc/rotors.conf', help="Path to config file specifying rotor ports and names.")
    args = parser.parse_args()

    # Parse config file.
    default_hostname = 'localhost'
    config = ConfigParser()
    config.read_file(open(args.config_file, 'r'))

    # Connect to rotctld instances specified in config file.
    for rotor in config.sections():
        hostname = config.get(rotor, 'rotctld_host', fallback=default_hostname)
        port = int(config.get(rotor, 'rotctld_port'))
        name = rotor

        #add rotor resolution to rotor increments
        DEFAULT_INCREMENT = 1
        resolution = float(config.get(rotor, 'resolution', fallback=DEFAULT_INCREMENT))
        increments[name] = resolution

        #connect to rotctld
        rotator = ROTCTLD(hostname=hostname, port=port)
        rotator.connect()
        rotators[name] = rotator

        (az, el) = rotators[name].get_azel()
        current_setpoints[name] = {'azimuth': az, 'elevation': el}
        current_positions[name] = current_setpoints[name]

    # Run the Flask app, which will block until CTRL-C'd.
    socketio.run(app, host='0.0.0.0', port=args.listen_port)

    # Close the rotator connection.
    for rotator in rotators.values():
        rotator.close()

