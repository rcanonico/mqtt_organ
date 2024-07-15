"""
Copyright (c) 2018 Ian Shatwell
Copyright (c) 2024 Roberto Canonico
The above copyright notice and the LICENSE file shall be included with
all distributions of this software
"""
import organserver
import getopt
import sys
import os.path
import configparser
import time
import paho.mqtt.client as mqtt
import signal

DEBUG = False
VERBOSE = False
configfile = ""
    
def signal_handler(sig, frame):
    global DEBUG
    global cont
    if DEBUG:
        print ("SOUND: Shutdown signal caught")
    cont = False

def on_mqtt_connect(client, userdata, flags, rc):
    if rc == 0:
        global mqttconnected
        global mqtttopic
        global VERBOSE
        if VERBOSE:
            print("SOUND: Connected to MQTT broker")
        mqttconnected = True
        mqttclient.on_message = on_mqtt_message
        subsuccess = -1
        while subsuccess != 0:
            if VERBOSE:
                print ("SOUND: Subscribing to {}".format(mqtttopic))
            (subsuccess, mid) = mqttclient.subscribe(mqtttopic)
            time.sleep(1)
        if VERBOSE:
            print ("SOUND: Subscribed to {}".format(mqtttopic))
    else:
        print("SOUND: MQTT connection failed. Error {} = {}".format(rc, mqtt.error_string(rc)))
        sys.exit(3)

def on_mqtt_disconnect(client, userdata, rc):
    global mqttconnected
    global mqttclient
    mqttconnected = False
    if VERBOSE:
        print("SOUND: Disconnected from MQTT broker. Error {} = {}".format(rc, mqtt.error_string(rc)))
    # rc == 0 means disconnect() was called successfully
    if rc != 0:
        if VERBOSE:
            print("SOUND: Reconnect should be automatic")

def connect_to_mqtt(broker, port):
    global mqttconnected
    global mqttclient
    if VERBOSE:
        print ("SOUND: Connecting to MQTT broker at {}:{}".format(broker, port))
    mqttconnected = False
    mqttclient.on_connect = on_mqtt_connect
    mqttclient.on_disconnect = on_mqtt_disconnect
    mqttclient.loop_start()
    while mqttconnected is not True:
        try:
            mqttclient.connect(broker, port, 5)
            while mqttconnected is not True:
                time.sleep(0.1)
        except Exception as e:
            print ("SOUND: Exception {} while connecting to broker".format(e))

def on_mqtt_message(client, userdata, message):
    global totaltime
    global numevents
    data = message.payload.decode()
    starttime = time.time()
    if DEBUG:
        print ("SOUND: {:6.3f}: {}".format(starttime, data))
    pieces = data.split()
    while len(pieces) > 0:
        cmd = pieces[0]
        del pieces[0]
        # Note message
        if cmd == "N":
            k = int(pieces[0])
            n = int(pieces[1])
            v = int(pieces[2])
            if 0 <= n < 128:
                if v > 0:
                    if DEBUG:
                        print("keyboard_key_down(k=%d, n=%d) - v=%d" % (k, n, v))
                    sorgan.keyboard_key_down(k, n)
                elif v == 0:
                    if DEBUG:
                        print("keyboard_key_up(k=%d, n=%d) - v=%d" % (k, n, v))
                    sorgan.keyboard_key_up(k, n)
            del pieces[0]
            del pieces[0]
            del pieces[0]
        # Stop message
        if cmd == "S":
            n = int(pieces[0])
            a = int(pieces[1])
            if a == 0:
                sorgan.stop_off(n)
            elif a == 1:
                sorgan.stop_on(n)
            elif a == 2:
                sorgan.toggle_stop(n)
            del pieces[0]
            del pieces[0]
        # Mode message
        if cmd == "M":
            n = int(pieces[0])
            sorgan.all_off()
            sorgan.find_changes()
            sorgan.set_instrument(n)
            del pieces[0]
        # Transpose message
        if cmd == "T":
            t = int(pieces[0])
            sorgan.transpose(t)
            del pieces[0]
        # Volume control
        if cmd == "V":
            v = int(pieces[0])
            sorgan.set_volume(v)
            del pieces[0]
            
    # Handle the state changes
    sorgan.find_changes()
    endtime = time.time()
    totaltime = totaltime + (endtime - starttime)
    numevents = numevents + 1

if __name__ == "__main__":
    # Check command line startup options
    try:
        opts, args = getopt.getopt(sys.argv[1:], "hdvc:", ["help", "debug", "verbose", "config="])
    except getopt.GetoptError:
        sys.exit(1)
    for opt, arg in opts:
        if opt in ("-h", "--help"):
            print ("Options are -d [--debug], -v [--verbose], -c [--config=]<configfile>")
            sys.exit(0)
        elif opt in ("-d", "--debug"):
            DEBUG = True
            print ("SOUND: Debug mode enabled")
        elif opt in ("-v", "--verbose"):
            VERBOSE = True
            print ("SOUND: Verbose mode enabled")
        elif opt in ("-c", "--config"):
            configfile = arg
            print ("SOUND: Config file: {}".format(configfile))

    if configfile == "":
        if os.path.isfile(sys.path[0] + "/organ.conf"):
            configfile = sys.path[0] + "/organ.conf"
        elif os.path.isfile("~/.organ.conf"):
            configfile = "~/.organ.conf"
        elif os.path.isfile("/etc/organ.conf"):
            configfile = "/etc/organ.conf"
            
    # Read config file
    try:
        if VERBOSE:
            print ("SOUND: Using config file: {}".format(configfile))
        config = configparser.ConfigParser()
        config.read(configfile)
        num_keyboards = config.getint("Global", "numkeyboards")
        this_keyboard = config.getint("Local", "thiskeyboard")
        localsection = "Console" + str(this_keyboard)
        mqttbroker = config.get("Global", "mqttbroker")
        mqttport = config.getint("Global", "mqttport")
        mqtttopic = config.get(localsection, "topic")
        print("topic=",mqtttopic)
    except configparser.Error as e:
        print ("SOUND: Error parsing the configuration file")
        print (e.message)
        sys.exit(2)

    sorgan = organserver.OrganServer(VERBOSE, DEBUG, configfile)
    
    #Synth test
    print("Testing synth")
    sorgan.fs.noteon(1, 60, 30)
    sorgan.fs.noteon(1, 67, 30)
    sorgan.fs.noteon(1, 76, 30)
    time.sleep(1.0)
    sorgan.fs.noteoff(1, 60)
    sorgan.fs.noteoff(1, 67)
    sorgan.fs.noteoff(1, 76)
    time.sleep(1.0)

    mqttclient = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1, "Server" + localsection)
    connect_to_mqtt(mqttbroker, mqttport)

    # Register signal handler
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    cont = True
    totaltime = 0.0
    numevents = 0
    while cont is True:
        # Incoming messages are handled by the mqtt callback
        time.sleep(1)

    if VERBOSE:
        print ("SOUND: Cleaning up")
        mqttclient.disconnect()
        mqttclient.loop_stop()
        if numevents > 0:
            print ("SOUND: Average event process time = {:4.2f}ms".format(1000 * totaltime / numevents))
        else:
            print ("SOUND: No events received")
    sorgan.cleanup()
