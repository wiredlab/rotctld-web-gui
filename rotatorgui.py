#!/usr/bin/env python3
#
#   ROTCTLD Basic Web GUI
#
#   Copyright (C) 2018  Mark Jessop <vk5qi@rfhead.net>
#   Released under GNU GPL v3 or later
#
import json
import flask
from flask_socketio import SocketIO
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
            response_split = response.split('\n')
            _current_azimuth = float(response_split[0])
            _current_elevation = float(response_split[1])
            return (_current_azimuth, _current_elevation)
        except:
            logging.error("Could not parse position: %s" % response)
            return (None,None)


    def halt(self):
        """ Immediately halt rotator movement, if it support it """
        self.send_command('S')

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


def flask_emit_event(event_name="none", data={}, client_id=None):
    """ Emit a socketio event to any clients. """
    socketio.emit(event_name, data, namespace='/update_status', room=client_id)


# SocketIO Handlers

@socketio.on('client_connected', namespace='/update_status')
def client_connected(data):
    #display current position
    read_position(data)


@socketio.on('update_setpoint', namespace='/update_status')
def update_azimuth_setpoint(data):
    rotator_key = data['rotator_key']

    #current setpoints
    set_azimuth = current_setpoints[rotator_key]['azimuth']
    set_elevation = current_setpoints[rotator_key]['elevation']

    motor = data['motor']

    def update_setpoint_value(setpoint):
        """
        Update setpoint: if data contains 'delta', update with increment,
        otherwise update to an absolute value.
        """

        is_increment_update = ('delta' in list(data))
        if is_increment_update:
            setpoint += data['delta']
        else:
            setpoint = float(data['val'])
        return setpoint

    #set new setpoints
    if motor == 'azimuth':
        set_azimuth = update_setpoint_value(set_azimuth)
    elif motor == 'elevation':
        set_elevation = update_setpoint_value(set_elevation)

    #limit azi and ele to 0-360 and 0-90 for setpoint display purposes,
    #though rotctld will take care of this automatically
    set_azimuth = set_azimuth % 360
    if set_elevation > 90.0:
            set_elevation = 90.0
    elif set_elevation < 0.0:
            set_elevation = 0.0

    #set rotctld to current setpoint
    rotators[data['rotator_key']].set_azel(set_azimuth, set_elevation)

    #update book-keeping
    current_setpoints[rotator_key]['azimuth'] = set_azimuth
    current_setpoints[rotator_key]['elevation'] = set_elevation

    #update client display
    flask_emit_event('setpoint_event', current_setpoints[rotator_key], request.sid)

@socketio.on('halt_rotator', namespace='/update_status')
def halt_rotator(data):
    name = data['rotator_key']
    rotators[name].halt()

    #update setpoint to current position
    (_az, _el) = rotators[name].get_azel()
    current_setpoints[name] = {'azimuth': _az, 'elevation': _el}
    flask_emit_event('setpoint_event', current_setpoints[name], request.sid)

@socketio.on('get_position', namespace='/update_status')
def read_position(data):
    rotor_key = data['rotator_key']
    (_az, _el) = rotators[rotor_key].get_azel()

    if (_az == None):
        return
    else:
        current_position = {}
        current_position['azimuth'] = _az
        current_position['elevation'] = _el

        #display current position
        flask_emit_event('position_event', current_position, request.sid)

        #display current setpoint
        flask_emit_event('setpoint_event', current_setpoints[rotor_key], request.sid)


if __name__ == "__main__":
    import argparse
    from configparser import ConfigParser

    parser = argparse.ArgumentParser()
    parser.add_argument("-l", "--listen_port",default=5001,help="Port to run Web Server on. (Default: 5001)")
    parser.add_argument("--config-file", default='/usr/local/etc/rotors.conf', help="Path to config file specifying rotor ports and names.")
    args = parser.parse_args()

    # Parse config file.
    HOSTNAME = 'localhost'
    config = ConfigParser()
    config.readfp(open(args.config_file, 'r'))

    # Connect to rotctld instances specified in config file.
    for rotor in config.sections():
        port = int(config.get(rotor, 'rotctld_port'))
        name = rotor

        #add rotor resolution to rotor increments
        DEFAULT_INCREMENT = 1
        resolution = float(config.get(rotor, 'resolution', fallback=DEFAULT_INCREMENT))
        increments[name] = resolution

        #connect to rotctld
        rotator = ROTCTLD(hostname=HOSTNAME, port=port)
        rotator.connect()
        rotators[name] = rotator

        current_setpoints[name] = {'azimuth': 0.0, 'elevation': 0.0}

    # Run the Flask app, which will block until CTRL-C'd.
    socketio.run(app, host='0.0.0.0', port=args.listen_port)

    # Close the rotator connection.
    for rotator in rotators:
        rotator.close()

