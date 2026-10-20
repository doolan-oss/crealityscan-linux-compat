#!/usr/bin/python3
"""Independent Pika raw capture. See README for format and current limitations."""
import argparse
from datetime import datetime,timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
from device import discover,Control
from analyze import analyze
from illumination import PRESETS,prepare

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent.parent

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--list',action='store_true',help='Discover verified Pika endpoints; no device opens')
    ap.add_argument('--serial',help='Required when more than one Pika is attached')
    ap.add_argument('--seconds',type=float,default=3,help='0.2–30 seconds (default 3)')
    ap.add_argument('--fps',type=int,choices=(10,15,20,30,40,50,60,70,80,90,100,110,120),default=None,help='Default 30; synchronized mixed mode requires 90')
    ap.add_argument('--color',action='store_true',help='Also request native 30 fps MJPEG colour capture')
    ap.add_argument('--laser-test',action='store_true',help='Experimental: enable only property 3; capture limited to 3 seconds; aim at an object first')
    ap.add_argument('--illumination-test',choices=tuple(PRESETS),help='Opt-in named illumination experiment; capture <=3 s, power/current unchanged')
    ap.add_argument('--sync-mode',choices=('mixed',),help='Verified mixed laser/speckle capture <=3 s: 90 fps GREY + 30 fps colour, white LEDs off')
    ap.add_argument('--scan-mode',choices=('marker-laser',),help='Record up to 30 s of stereo blue laser + blue marker illumination at 120 fps; white LEDs off, no colour stream')
    ap.add_argument('--memory-stage',action='store_true',help='Stage raw capture on verified /tmp tmpfs, then copy after controls restore; automatic for --scan-mode')
    ap.add_argument('--exposure',type=int,default=1000,help='IR exposure property 2026, 10–2500 in steps of 10; default 1000')
    ap.add_argument('--output',type=Path,help='New directory; defaults to recordings/pika-<timestamp>')
    args=ap.parse_args()
    if args.scan_mode:
        if args.sync_mode or args.illumination_test or args.laser_test or args.color:
            ap.error('--scan-mode cannot combine with other mode/illumination options or --color')
        if args.fps not in (None,120):ap.error('Marker laser capture requires --fps 120')
        args.fps=120;args.illumination_test='marker-laser';args.memory_stage=True
    if args.sync_mode:
        if args.illumination_test or args.laser_test:ap.error('--sync-mode cannot combine with illumination/laser tests')
        if args.fps not in (None,90):ap.error('Verified mixed sync mode requires --fps 90')
        args.fps=90;args.color=True;args.illumination_test='mixed-dual'
    if args.fps is None:args.fps=30
    if not .2<=args.seconds<=30 or not 10<=args.exposure<=2500 or args.exposure%10:
        ap.error('Invalid duration or exposure')
    if args.laser_test and args.seconds>3:ap.error('--laser-test is limited to 3 seconds')
    if args.illumination_test and not args.scan_mode and (args.seconds>3 or args.laser_test):ap.error('Illumination test needs <=3 seconds and cannot combine with --laser-test')
    devices=discover()
    if args.list: print(json.dumps(devices,indent=2));return 0
    selected=[d for d in devices if args.serial is None or d['serial']==args.serial]
    if len(selected)!=1:raise RuntimeError('Connect exactly one Pika or select --serial; use --list')
    device=selected[0];nodes=device['nodes']
    for key in ('0:0','0:1')+(('2:0','2:1') if args.color else ()):
        if key not in nodes:raise RuntimeError(f'Missing endpoint {key}')
    # Shared with the existing USB launchers. No kill/restart of another app.
    lock_root=Path(os.environ.get('PIKA_LOCK_ROOT',str(ROOT))).resolve()
    if not lock_root.is_dir():raise RuntimeError('PIKA_LOCK_ROOT must exist')
    lock=open(lock_root/'.creality-usb-bridge-test.lock','a')
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:raise RuntimeError('Another USB recorder/scan launcher holds the scanner lock')
    app_locks=[]
    for prefix in ('prefix-crealityscan','prefix-crealityscan-blue-laser'):
        path=lock_root/prefix/'.creality-launch.lock'
        if path.exists():
            item=path.open('r')
            try:fcntl.flock(item,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:raise RuntimeError('A working scan launcher is active; close it first')
            app_locks.append(item)
    running=subprocess.run(['/usr/bin/pgrep','-x','CrealityScan.ex'],capture_output=True)
    if running.returncode==0:raise RuntimeError('Close CrealityScan before recording')
    if running.returncode!=1:raise RuntimeError('Could not check application ownership')
    owners=subprocess.run(['/usr/bin/fuser',*nodes.values()],capture_output=True,text=True)
    if owners.returncode==0:raise RuntimeError('Camera endpoints are in use: '+owners.stdout.strip())
    if owners.returncode!=1:raise RuntimeError('Could not check camera ownership: '+owners.stderr)
    out=(args.output or ROOT/'recordings'/('pika-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))).resolve()
    out.parent.mkdir(parents=True,exist_ok=True)
    # Account conservatively for > requested rate and variable compressed images.
    need=int(args.seconds*(1280*960*240+(1280*960*3*60 if args.color else 0)))+2*1024**3
    if shutil.disk_usage(out.parent).free<need:raise RuntimeError(f'Need {need/1024**3:.1f} GiB free')
    if args.memory_stage:
        fs=subprocess.run(['/usr/bin/findmnt','-n','-o','FSTYPE','-T','/tmp'],capture_output=True,text=True,check=True)
        if fs.stdout.strip()!='tmpfs':raise RuntimeError('--memory-stage requires /tmp to be tmpfs; no mount changes made')
        available=int(next(l.split()[1] for l in Path('/proc/meminfo').read_text().splitlines() if l.startswith('MemAvailable:')))*1024
        if min(available,shutil.disk_usage('/tmp').free)<need:
            raise RuntimeError(f'Memory staging requires {need/1024**3:.1f} GiB available RAM and tmpfs space')
    out.mkdir()  # exclusive: never overwrite a recording
    capture_out=Path(tempfile.mkdtemp(prefix='pika-native-',dir='/tmp')) if args.memory_stage else out
    manifest={'format_version':1,'created_utc':datetime.now(timezone.utc).isoformat(),
              'device':device,'requested_ir_fps':args.fps,'requested_color_fps':30 if args.color else None,
              'duration_seconds':args.seconds,'mode':('marker-laser-raw' if args.scan_mode else 'synchronized-mixed' if args.sync_mode else 'illumination-test' if args.illumination_test else 'laser-gate-test' if args.laser_test else 'ambient-raw')+('; named volatile illumination preset' if args.illumination_test else '; existing firmware work mode retained'),
              'scan_mode':args.scan_mode,'tracking_performed':False,
              'memory_staging':args.memory_stage,'capture_staging_path':str(capture_out) if args.memory_stage else None,
              'laser_gate_requested':args.laser_test,'illumination_test':args.illumination_test,
              'illumination_preset':PRESETS.get(args.illumination_test),'synchronized_mode':args.sync_mode,
              'camera_identity':'Raw transport; use demux.py for offline left/right and phase separation',
              'exposure_property_2026':args.exposure,'independent_cold_start_verified':False,
              'sources_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in HERE.iterdir() if p.suffix in ('.c','.py')},
              'capture_binary_sha256':hashlib.sha256((HERE/'capture').read_bytes()).hexdigest(),
              'status':'initializing','pid':os.getpid()}
    (out/'controller-process-maps.txt').write_text(Path('/proc/self/maps').read_text())
    def save(): (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    save();print('Recording:',out,flush=True)
    control=None;child=None;interrupted=[];error=None;result=1
    def signal_stop(sig,frame):
        interrupted.append(sig)
        if child is not None and child.poll() is None:child.send_signal(sig)
    for sig in (signal.SIGINT,signal.SIGTERM,signal.SIGHUP):signal.signal(sig,signal_stop)
    with (out/'control.jsonl').open('w') as log:
        def record_control(row):log.write(json.dumps({'monotonic_ns':__import__('time').monotonic_ns(),**row})+'\n');log.flush()
        try:
            control=Control(nodes['0:0'],record_control)
            manifest['properties_before']={str(p):control.get(p) for p in (3,152,153,2026)};save()
            for prop in (3,152,153):control.set(prop,0)
            control.set(2026,args.exposure)
            if args.illumination_test:
                manifest['illumination_properties_before']=prepare(control,args.illumination_test);save()
            if args.laser_test:control.set(3,1,allow_laser_test=True)
            if interrupted:raise InterruptedError('Interrupted before capture')
            manifest['status']='capturing';save()
            with (out/'capture.log').open('w') as log_capture:
                child=subprocess.Popen([str(HERE/'capture'),str(capture_out),str(args.seconds),str(args.fps),nodes['0:0'],nodes['0:1'],
                                        nodes['2:0'] if args.color else '-',nodes.get('2:1','-'),'30'],stdout=log_capture,stderr=subprocess.STDOUT)
                if interrupted: child.send_signal(interrupted[-1])
                try:result=child.wait(timeout=args.seconds+15)
                except subprocess.TimeoutExpired:
                    child.terminate()
                    try:child.wait(timeout=2)
                    except subprocess.TimeoutExpired:child.kill();child.wait()
                    raise RuntimeError('Capture watchdog expired; restoring illumination')
            manifest['capture_exit_code']=result
        except Exception as e:error=str(e)
        finally:
            if child is not None and child.poll() is None:
                child.terminate()
                try:child.wait(timeout=2)
                except subprocess.TimeoutExpired:child.kill();child.wait()
            if control:
                try:control.close();manifest['controls_restored']=True
                except Exception as e:manifest['controls_restored']=False;error=(error or '')+'; '+str(e)
    if args.memory_stage:
        print('Capture stopped; controls restoration attempted. Saving RAM capture to disk...',flush=True)
        save()
        try:
            for source in capture_out.iterdir():
                if not source.is_file():raise RuntimeError('Unexpected staging entry')
                destination=out/source.name
                with source.open('rb') as src,destination.open('xb') as dst:
                    shutil.copyfileobj(src,dst,1024*1024);dst.flush();os.fsync(dst.fileno())
                with source.open('rb') as src,destination.open('rb') as dst:
                    if hashlib.file_digest(src,'sha256').digest()!=hashlib.file_digest(dst,'sha256').digest():
                        raise RuntimeError('Staging copy checksum mismatch')
            shutil.rmtree(capture_out)  # only our private staging directory, after verified copying
            manifest['staging_copy_verified']=True
        except Exception as e:
            error=(error or '')+f'; staging copy: {e}; original staging files retained at {capture_out}'
    try:
        summary=analyze(out)
        manifest['summary']=summary
        for s in summary.values():
            if (not s['frames'] or s['error_flagged_frames'] or s['empty_frames']
                or s.get('unexpected_payload_sizes',0) or s['malformed_metadata_buffers']
                or s['frames_with_pts_scr'] != s['frames']):result=1
    except Exception as e:error=(error or '')+'; analysis: '+str(e)
    manifest['status']='interrupted' if interrupted else 'failed' if error or result else 'passed'
    manifest['error']=error;save()
    print(json.dumps(manifest.get('summary',{}),indent=2))
    print('Status:',manifest['status'])
    if error:print(error,file=sys.stderr)
    return result if not error else 1

if __name__=='__main__':
    try:sys.exit(main())
    except (OSError,RuntimeError) as e:print('Recorder refused/failed:',e,file=sys.stderr);sys.exit(1)
