"""Opt-in volatile Pika illumination experiments, named from the installed SDK.
No current/power, calibration, flash, firmware or arbitrary property writes.
"""
GATES=(3,6,152,153,156,157,158,219,221)
MODIFIERS=(98,178,179,192)
PRESETS={'off':{},'laser1':{3:1},'laser2':{152:1},'laser3':{153:1},
         'laser4':{219:1},'rgb-white':{156:1},'ir-white':{157:1},
         'ir-blue':{158:1},'flood':{6:1},'long-range':{221:1},
         'laser-blue':{3:1,158:1},'ir-switch':{98:1,3:1},
         'ir-work':{179:1,3:1},'ir-mask':{178:1,158:1}}
PRESETS['mixed-dual']={192:4,3:1,152:1}
PRESETS['mixed-white']={192:4,3:1,152:1,156:1}
PRESETS['mixed-blue']={192:4,3:1,152:1,158:1}
PRESETS['marker-laser']={192:0,3:1,158:1}
PRESETS['speckle-gate-off']={192:6}
for mode in range(7):PRESETS[f'line-mode-{mode}']={192:mode,3:1}

def allowed(prop,value):
    return (prop in GATES+(98,178,179) and value in (0,1)) or (prop==192 and value in range(7))

def prepare(control,preset):
    # Save all baseline controls before writing. Restore gates last so mode
    # restoration occurs with experimental illumination switched back off.
    before={p:control.get(p) for p in GATES+MODIFIERS}
    for p in GATES:control.set(p,0,allow_illumination_test=True)
    for p in MODIFIERS:
        control.set(p,0,allow_illumination_test=True)
    for p,v in PRESETS[preset].items():
        control.set(p,v,allow_illumination_test=True)
    return before
