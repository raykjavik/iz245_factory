"""Shared receiver SCPI constants and frequency axes. No application dependencies."""

import re
import numpy as np
import math

DBM_TO_DBUV_50_OHM = 90 + 10 * math.log10(50)

FREQ_AXIS_FULL_RANGE_HZ =np.concat([
    np.arange(1e6,1e7,500000),
    np.arange(1e7,1e8,1000000),
    np.arange(1e8,8e9,10000000),
    np.array([7999999900,8000000000])
]).astype(int)

FREQ_AXIS_CH2_HZ = np.concat([
    np.arange(1e5,1e6,100000),
    np.arange(1e6,1e7,500000),
    np.arange(1e7,9e7,1000000),
    np.array([89999900,90000000])
]).astype(int)

FREQ_AXIS_PRES_10M_HZ = np.concat([
    np.arange(100_000,10_000_000,	100000),
    np.arange(10_000_000,20_000_000,250000),
    np.array([19999900,20000000])
]).astype(int)

FREQ_AXIS_PRES_20M_HZ = np.concat([
    np.arange(1000000,8000000,250000),
    np.arange(8000000,22000000,100000),
    np.arange(22000000,30000000,250000),
    np.array([29999900,30000000])
]).astype(int)

FREQ_AXIS_PRES_30M_HZ = np.concat([
    np.arange(10000000,30000000,100000.0),
    np.arange(30000000,40000000,250000.0),
    np.array([39999900,40000000])
]).astype(int)


FREQ_AXIS_PRES_LOW_HZ = np.concat([
    np.arange(30000000,70000000,1000000),
    np.arange(70000000,520000000,2000000),
    np.array([519999900,520000000])
]).astype(int)

FREQ_AXIS_PRES_HIGH_HZ = np.concat([
    np.arange(520000000,8000000000,10000000.0),
    np.array([7999999900,8000000000])
]).astype(int)

FREQ_AXIS_BASEBAND_HZ = np.concat([
    np.arange(100000,300000,10000.0),
    np.arange(300000,500000,25000.0),
    np.arange(500000,10000000,500000.0),
    np.arange(10000000,90000000,1000000.0),
    np.array([89999900,90000000.0]),
]).astype(int)


_BAND_5K = "BAND 5k"

_CAL_ON = "syst:cal on"
_CAL_OFF = "syst:cal off"
_IFBAND_AUTO = "FILTerbank:MODE AUTO"
_BASE_BAND =  "FREQ:PLAN:INPUT:MODE SIN;:FREQ:PLAN:BAND1:THR 80MHz,"

_RF1 =  "FREQ:PLAN:INPUT:MODE SIN;:FREQ:PLAN:BAND1:THR 1MHz"
_RF2 =  "FREQ:PLAN:INPUT:MODE MUL;: FREQ:PLAN:BAND1:THR 90MHz"

_GAIN_ON = "INP:GAIN ON"
_GAIN_OFF = "INP:GAIN OFF"
_GAIN_10DB = "INP:GAIN -10"
_GAIN_20DB = "INP:GAIN -20"

_IFBAND_MANUAL = "FILTerbank:MODE MANUAL;:FILTerbank "


_PRESELECTOR_OFF = "input:preselector off;: inp:preselector:path bypass"
_PRESELECTOR_ON = "input:preselector auto"
_PG_ON = "input:preselector:gain on"
_PG_OFF = "input:preselector:gain off"
_PRES_PATH = "inp:preselector:path "
_RST = "*RST"
_RSOC_OUT = "ROSC:SOUR OUT"




def sweep_bandwidth_hz(commands):
    """Final configured BAND/RBW in Hz; None if not specified in this sweep."""
    bandwidth = None
    for command in commands:
        for part in command.split(';'):
            match = re.fullmatch(r':?BAND(?:WIDTH)?\s+([0-9.eE+-]+)\s*([kKmMgG]?)(?:[hH][zZ])?',part.strip(),re.IGNORECASE)
            if match:
                bandwidth = float(match[1])*{'':1,'k':1e3,'m':1e6,'g':1e9}[match[2].lower()]
    return bandwidth
