"""
Copyright (c) 2024 Roberto Canonico
The above copyright notice and the LICENSE file shall be included with
all distributions of this software
"""
import sys
import os.path
import configparser
import time
import copy
import fluidsynth

NUM_KEYS = 128
FIRST_KEY = 35
LAST_KEY = 97

class OrganServer:
    def __init__(self, verbose_flag, debug_flag, configfile):
        self.verbose = verbose_flag
        self.debug = debug_flag
        # Read config file
        try:
            if self.verbose:
                print ("SOUND: Using config file: {}".format(configfile))
            self.config = configparser.ConfigParser()
            self.config.read(configfile)
            self.num_keyboards = self.config.getint("Global", "numkeyboards")
            self.this_keyboard = self.config.getint("Local", "thiskeyboard")
            self.localsection = "Console" + str(self.this_keyboard)
            self.mlist = self.config.get(self.localsection, "modes")
            self.modes = self.mlist.split(",")
        except configparser.Error as e:
            print ("SOUND: Error parsing the configuration file")
            print (e.message)
            raise ValueError('Error parsing the configuration file')
       
        if self.verbose:
            print ("SOUND: This is server {} in the range 0-{}".format(self.this_keyboard, self.num_keyboards - 1))
        self.channels = [0, 1, 2, 3, 4, 5, 6, 7, 8, 10, 11, 12, 13, 14, 15]  # Skip channel 9 (usually drums)
        self.allkeys = [[0] * NUM_KEYS for _ in range(self.num_keyboards)]  # State of keys on all manuals
        self.keys = [0] * NUM_KEYS  # Aggregate state of keys
        self.prevkeys = [0] * NUM_KEYS
        self.num_stops = 1
        self.stops = [0] * self.num_stops  # State of stops on this manual
        self.prevstops = [0] * self.num_stops
        self.patches = [0]
        self.stopnames = [""]  # Only used for cosmetic purposes
        self.modeindex = 0
        self.sfid = 0
        self.fs = None
        self.transposeamount = 0
        self.set_instrument(self.modeindex)
        self.volume = 127

    def cleanup(self):
        if self.fs is not None:
            self.fs.delete()

    def set_instrument(self, n):
        self.all_off()
        self.modeindex = n
        self.load_instrument(self.modes[self.modeindex])

    def load_instrument(self, inst):
        # Initialise synth connections
        if self.verbose:
            print ("SOUND: Loading instrument: {}".format(inst))
        if self.fs is not None:
            self.fs.delete()
            self.fs = None
        #self.fs = pyfs.Synth(fsgain, 44100.0, 256, 16, 2, 64, 0, 0)
        self.soundfont = self.config.get(self.localsection + inst, "soundfont")
        print("soundfont=", self.soundfont)
        self.fsgain = self.config.getfloat(self.localsection + inst, "fsgain")
        if self.debug:
            print ("SOUND: Starting FluidSynth with gain={}".format(self.fsgain))
        self.fs = fluidsynth.Synth(gain=self.fsgain)
        self.fs.start()
#        self.fs.start(driver="alsa")
        self.sfid = self.fs.sfload(self.soundfont)
        self.num_stops = self.config.getint(self.localsection + inst, "numstops")
        print("numstops=",self.num_stops)
        if self.num_stops > len(self.channels):
            print ("SOUND: More stops than channels available")
            sys.exit(4)
        self.patches = [0] * self.num_stops
        self.stopnames = [""] * self.num_stops
        if self.verbose:
            print ("SOUND: Using {} stops from {}".format(self.num_stops, self.soundfont))
        for s in range(0, self.num_stops):
            strs = str(s)
            self.patches[s] = self.config.getint(self.localsection + inst, "stop%s" % strs)
            self.stopnames[s] = self.config.get(self.localsection + inst, "stopname%s" % strs)
            self.fs.program_select(self.channels[s], self.sfid, 0, self.patches[s])
            if self.verbose:
                print ("SOUND: Configured stop {} to use patch {} ({})".format(s, self.patches[s], self.stopnames[s]))
        self.stops = [0] * self.num_stops
        self.prevstops = [0] * self.num_stops

    def start_note(self, channel, note, velocity=127):
        if (note >= 0) and (note < NUM_KEYS):
            channel = self.channels[channel]
            if self.debug:
                print ("SOUND: Start playing channel {}, note {}".format(channel, note))
            self.fs.noteon(channel, note + self.transposeamount, velocity)

    def stop_note(self, channel, note):
        if (note >= 0) and (note < NUM_KEYS):
            channel = self.channels[channel]
            if self.debug:
                print ("SOUND: Stop playing channel {}, note {}".format(channel, note))
            self.fs.noteoff(channel, note + self.transposeamount)

    def find_changes(self):
        # Look for coupled key press changes and collapse to a single list
        for n in range(FIRST_KEY, LAST_KEY):
            self.prevkeys[n] = self.keys[n]
            self.keys[n] = 0
            for manual in self.allkeys:
                if manual[n] > 0:
                    self.keys[n] = 1
                    break
        # If a key has changed then change the notes playing for each active stop
        for n in range(FIRST_KEY, LAST_KEY):
            if self.keys[n] > self.prevkeys[n]:
                for s in range(0, self.num_stops):
                    if self.stops[s] > 0:
                        self.start_note(s, n, self.volume)
            if self.keys[n] < self.prevkeys[n]:
                for s in range(0, self.num_stops):
                    if self.stops[s] > 0:
                        self.stop_note(s, n)
        # If a stop has changed then change the notes playing for each active key
        # This may cause duplicate starts/stops with previous block, but this does not really matter
        for s in range(0, self.num_stops):
            if self.stops[s] > self.prevstops[s]:
                for n in range(FIRST_KEY, LAST_KEY):
                    if self.keys[n] > 0:
                        self.start_note(s, n, self.volume)
            if self.stops[s] < self.prevstops[s]:
                for n in range(FIRST_KEY, LAST_KEY):
                    if self.keys[n] > 0:
                        self.stop_note(s, n)
            self.prevstops[s] = self.stops[s]

    def toggle_stop(self, stop):
        if self.stops[stop] == 0:
            self.stop_on(stop)
        else:
            self.stop_off(stop)

    def stop_on(self, stop):
        if (stop >= 0) and (stop < self.num_stops):
            if self.debug:
                print("SOUND: Stop on:{} ({}={})".format(stop, self.patches[stop], self.stopnames[stop]))
            self.stops[stop] = 1

    def stop_off(self, stop):
        if (stop >= 0) and (stop < self.num_stops):
            if self.debug:
                print("SOUND: Stop off:{} ({}={})".format(stop, self.patches[stop], self.stopnames[stop]))
            self.stops[stop] = 0

    def keyboard_key_down(self, keyboard, note):
        if self.debug:
            print ("SOUND: Note {} down on keyboard {}".format(note, keyboard))
        self.allkeys[keyboard][note] = 1

    def keyboard_key_up(self, keyboard, note):
        if self.debug:
            print ("SOUND: Note {} up on keyboard {}".format(note, keyboard))
        self.allkeys[keyboard][note] = 0

    def all_off(self):
        for k in range(0, self.num_keyboards):
            for n in range(FIRST_KEY, LAST_KEY):
                self.allkeys[k][n] = 0
        for s in range(0, len(self.stops)):
            self.stops[s] = 0

    def transpose(self, t):
        if self.debug:
            print ("SOUND: Transpose by {}".format(t))
        # Copy key state
        oldkeys = copy.deepcopy(self.allkeys)
        # Stop playing existing notes
        for k in range(0, self.num_keyboards):
            for n in range(FIRST_KEY, LAST_KEY):
                self.allkeys[k][n] = 0
        self.find_changes()
        # Copy key state back ready to restart notes
        self.allkeys = copy.deepcopy(oldkeys)
        self.transposeamount = t

    def set_volume(self, v):
        self.volume = v
        if self.debug:
            print ("SOUND: Volume now {}".format(self.volume))
