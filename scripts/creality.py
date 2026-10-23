#!/usr/bin/env python3
"""CrealityScan 4.3.2 on Linux: setup and launcher, confined to an owned prefix."""
import argparse,datetime,html,json,os,shutil,subprocess,sys
from contextlib import nullcontext
from integrity import installation_path, save_installation, verify_installation
import stateio
from pathlib import Path
from common import ROOT,RUNTIME_ROOT,LOCK,load,dependencies,digest,expect,owned,environment,sandbox,winpath
from display import open_display
from exports import default_dir,link_folders
from build import build
import fetch
import onboard

def logdir(c,label):
    logs=c['data_dir']/'logs'
    name=datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')+'-'+label
    with stateio.directory(logs,create=True) as fd:os.mkdir(name,mode=0o700,dir_fd=fd)
    return logs/name

def verify_build():
    hashes=json.loads((ROOT/'build/manifest.json').read_text())
    for name,h in hashes.items():expect(ROOT/'build'/name,h)
    return hashes

def wine(c,log,args,*,backend='disabled',extra=None,gpu=True,display=True,network=False,devices=(),seconds=90,workdir=None,exports=False):
    e=environment(c,log,backend);e.update({'CREALITY_RUNNER':str(c['runner']),'CREALITY_SOURCE':str(RUNTIME_ROOT),
          'CREALITY_WORKDIR':str(workdir or c['prefix']),'CREALITY_SECONDS':str(seconds)})
    if extra:e.update(extra)
    # Let the desktop focus the new window when launched from a menu or launcher;
    # Unity pauses startup while its window is in the background.
    startup=os.environ.get('DESKTOP_STARTUP_ID') or os.environ.get('XDG_ACTIVATION_TOKEN')
    if display and startup:e['DESKTOP_STARTUP_ID']=startup
    stateio.ensure_directory(c['prefix']/'home')
    installing=workdir is None and not installation_path(c).exists()
    code_files=[] if installing else list(verify_install(c))
    host_env={k:v for k,v in os.environ.items() if k not in ('LD_PRELOAD','LD_LIBRARY_PATH','PYTHONPATH','WINEPREFIX','WINEDLLOVERRIDES')}
    with open_display(c.get('display','desktop'),log) if display else nullcontext() as screen:
        cmd=sandbox(c,log,e,display=screen,gpu=gpu,network=network,devices=devices,installer=installing,
                    code_files=code_files,exports=c['exports_dir'] if exports else None)
        cmd+=[str(RUNTIME_ROOT/'scripts/run-wine.sh'),*map(str,args)]
        with stateio.open_file(log/'wine.log','xb')as f:code=subprocess.run(cmd,env=host_env,stdout=f,stderr=subprocess.STDOUT).returncode
    stateio.write_new(log/'exit-code.txt',str(code)+'\n')
    print('Exit:',code,'Logs:',log,flush=True);return code

def appdir(c):return c['prefix']/'drive_c/Program Files/CrealityScan'

def install(c):
    dependencies(c,installer=True);hashes=verify_build();lock=owned(c,create=True)
    prefix=c['prefix'];installed=installation_path(c)
    if installed.exists():
        verify_install(c);print('Already installed; verified without changing the prefix.');return
    if prefix.exists()and any(prefix.iterdir()):raise RuntimeError('Incomplete/populated prefix: preserved. Choose a NEW data_dir to retry; never reset it automatically.')
    prefix.mkdir(exist_ok=True);log=logdir(c,'install')
    print('Installing into new prefix:',prefix,flush=True)
    code=wine(c,log,[winpath(c['installer']),'/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/SP-',r'/DIR=C:\Program Files\CrealityScan','/LOG='+winpath(log/'installer.log')],
              extra={'LD_PRELOAD':'','WINEDLLOVERRIDES':'winemenubuilder.exe=d;opencl=b;mscoree,mshtml=d'},gpu=False,seconds=240)
    if code:raise RuntimeError('Installer failed; prefix/logs preserved')
    app=appdir(c);plugins=app/'CrealityScan_Data/Plugins/x86_64';sdk=plugins/'OrbbecSDK.dll'
    expect(sdk,LOCK['sdk_sha256'])
    if not (app/'CrealityScan.exe').is_file():raise RuntimeError('Installed executable missing')
    stateio.copy_file(sdk,plugins/'OrbbecSDK-stock.dll')
    sdklib=prefix/'drive_c/bridge-sdk';stateio.ensure_directory(sdklib);stateio.copy_file(sdk,sdklib/'OrbbecSDK.dll')
    for name in ('mf.dll','pikacam.dll'):stateio.copy_file(ROOT/'build'/name,app/name)
    stateio.copy_file(c['runner']/'lib/wine/x86_64-windows/mf.dll',app/'mfstock.dll')
    stateio.copy_file(ROOT/'build/sdk-proxy.dll',sdk,replace=True)
    for name in LOCK['dxvk']:stateio.copy_file(c['dxvk_dir']/name,app/name,replace=True)
    diag=prefix/'drive_c/diagnostics';stateio.ensure_directory(diag)
    for name in hashes:
        if name.endswith(('.exe','.dll')):stateio.copy_file(ROOT/'build'/name,diag/name)
    stateio.copy_file(app/'mfstock.dll',diag/'mfstock.dll')
    save_installation(c,hashes)
    print('Installation and app-local bridge deployment complete.')

def verify_install(c):
    return verify_installation(c,verify_build())

def diagnose(c):
    dependencies(c);lock=owned(c);verify_install(c)
    diag=c['prefix']/'drive_c/diagnostics';results={}
    for name,backend,extra in [('opencl-probe.exe','disabled',{}),('graphics-probe.exe','disabled',{}),('bridge-probe.exe','synthetic',{'PIKA_TEST_DLL':'mf.dll'})]:
        log=logdir(c,name);results[name]=wine(c,log,[winpath(diag/name)],backend=backend,extra=extra,workdir=diag)
    failed=[n for n,code in results.items() if code]
    if failed:raise RuntimeError(f'Diagnostic failure: {", ".join(failed)}. Logs: {c["data_dir"]/"logs"}. '
                                 f'If the GPU check failed, set gpu_name in the config to your GPU model (now "{c["gpu_name"]}")')
    print('PASSED: Windows GPU OpenCL kernel, rendered OpenGL pixel, synthetic MF source. No scanner was exposed.')

def prepare_exports(c):
    c['exports_dir'].mkdir(parents=True,exist_ok=True)
    kept,moved=link_folders(c['prefix'],c['exports_dir'])
    print('Exports and projects folder (the app\'s Documents):',c['exports_dir'],flush=True)
    if moved:print('Moved into it from the prefix:',', '.join(moved),flush=True)
    for folder in kept:print('Note: left in the prefix (name already used, other disk or unexpected link):',folder,flush=True)

def launch(c,mode,smoke=False):
    if mode=='wifi' and not c.get('allow_host_network',False):
        raise RuntimeError('Wi-Fi requires explicit allow_host_network=true; read the weaker isolation boundary in SECURITY.md')
    dependencies(c);lock=owned(c);verify_install(c);log=logdir(c,'smoke'if smoke else mode);prepare_exports(c)
    e={};nodes=[];scanner_lock=None
    if mode=='usb' and not smoke:
        from usb import prepare
        e,nodes,scanner_lock=prepare(c,log)
    if smoke:e['DXVK_HUD']='devinfo'
    code=wine(c,log,[winpath(appdir(c)/'CrealityScan.exe'),'-logFile',winpath(log/'Player.log')],
              extra=e,devices=nodes,network=mode=='wifi' and not smoke,seconds=35 if smoke else 0,workdir=appdir(c),exports=True)
    if smoke:
        player=stateio.read_text(log/'Player.log')if (log/'Player.log').exists()else ''
        success=code in (0,124) and any(s in player for s in ('HomeState','HomePanel')) and 'Direct3D' in player
        print('SMOKE:', 'PASSED'if success else 'NOT CONFIRMED; inspect Player.log')
        if not success:raise RuntimeError('App startup not confirmed')
    elif code:raise RuntimeError(f'App exited {code}')

def experimental(path,key,off):
    """List experimental scanner models, or turn one on or off in the config."""
    import models
    choices={m.key:m for m in models.MODELS.values() if m.experimental}
    if not path.exists():raise RuntimeError(f'No config at {path}; run setup first')
    raw=json.loads(path.read_text());load(path)
    enabled=raw.get('experimental_scanners') or []
    if not key:
        for m in choices.values():print(f'{m.key}: {m.name} (USB 2bc5:{m.pid}), {"on" if m.key in enabled else "off"}; {m.note}')
        return
    if key not in choices:raise ValueError(f'Unknown scanner "{key}"; choose from: {", ".join(choices)}')
    raw['experimental_scanners']=[k for k in enabled if k!=key]+([] if off else [key])
    temp=path.with_name(path.name+'.new')
    temp.write_text(json.dumps(raw,indent=2)+'\n');os.replace(temp,path)
    m=choices[key]
    if off:print(f'Experimental {m.name} support is off.')
    else:print(f'Experimental {m.name} support is on ({m.note}). Start CrealityScan with the scanner connected.\n'
               f'Afterwards, "python3 scripts/creality.py logs" saves the logs to attach to your report.\n'
               f'To turn it off again: python3 scripts/creality.py experimental {key} --off')

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--config',type=Path,default=ROOT/'config.local.json')
    sub=ap.add_subparsers(dest='command',required=True)
    p=sub.add_parser('setup',help='download pinned inputs, configure, install, check and add a menu entry')
    p.add_argument('--installer',help='CrealityScan_win_4.3.2.exe (default: found in Downloads)');p.add_argument('--gpu-name',help='default: detected OpenCL GPU')
    sub.add_parser('survey',help='describe connected Creality scanners for a hardware report (read-only)')
    p=sub.add_parser('experimental',help='list scanner models with experimental USB support, or turn one on')
    p.add_argument('model',nargs='?',help='for example sermoon-s1');p.add_argument('--off',action='store_true',help='turn it off again')
    sub.add_parser('logs',help='save the latest USB session\'s logs to one zip file for a bug report (serial numbers removed)')
    p=sub.add_parser('fetch',help='download the pinned Wine runner and DXVK');p.add_argument('--dir',type=Path,default=onboard.data_home()/'crealityscan-linux/runtime')
    p=sub.add_parser('configure');p.add_argument('--runner',required=True);p.add_argument('--installer',required=True);p.add_argument('--dxvk-dir',required=True);p.add_argument('--data-dir',required=True)
    for cmd in ('doctor','install','diagnose','smoke'):sub.add_parser(cmd)
    p=sub.add_parser('build');p.add_argument('--portable',action='store_true',help='link libyuv statically (release builds)')
    p=sub.add_parser('launch');p.add_argument('--mode',choices=('usb','wifi'),default='usb')
    args=ap.parse_args()
    if args.command=='survey':
        import survey;print(survey.report());return
    if args.command=='fetch':
        print('runner:',fetch.runner(args.dir));print('dxvk:',fetch.dxvk(args.dir));return
    if args.command=='setup':
        c=onboard.prepare(args.config,args.installer,args.gpu_name)
        dependencies(c,installer=True);onboard.helpers(c,build)
        onboard.set_aside_outdated(c);onboard.set_aside_incomplete(c)
        install(c);diagnose(c);onboard.finish(args.config);return
    if args.command=='experimental':
        experimental(args.config,args.model,args.off);return
    if args.command=='configure':
        c=json.loads((ROOT/'config/config.example.json').read_text())
        for key in ('runner','installer','dxvk_dir','data_dir'):c[key]=str(Path(getattr(args,key)).expanduser().resolve())
        c['exports_dir']=str(default_dir())
        with args.config.open('x')as f:json.dump(c,f,indent=2);f.write('\n')
        print('Created local config; edit GPU/environment settings before running install:',args.config);return
    c=load(args.config)
    if args.command=='doctor':
        dependencies(c,installer=True)
        required=['bwrap','python3','pgrep','fuser','timeout']
        if c['display']=='isolated':required.append('xwayland-satellite')
        missing=[x for x in required if not shutil.which(x)]
        if missing:raise RuntimeError('Missing commands: '+', '.join(missing))
        compilers=[x for x in ('clang','lld-link','llvm-dlltool','gcc') if not shutil.which(x)]
        print('Pinned dependency hashes verified. GPU validation happens at diagnose.')
        print('Building from source:', 'missing '+', '.join(compilers) if compilers else 'compilers found')
        print('Runner:',subprocess.check_output([str(c['runner']/'bin/wine'),'--version'],text=True).strip())
        print('Data directory:',c['data_dir'])
        print('Display:',c['display'],'| Exports folder:',c['exports_dir']);return
    if args.command=='logs':
        import collect,survey
        target,launched,app=collect.collect(c,[survey.read(d/'serial') for d in survey.scanners()])
        print('Collected:',launched or 'no launch logs','and',app or 'no app logs')
        print(f'Saved {target}\nAttach it to your GitHub issue. Serial numbers, Wi-Fi names and passwords, and your home\n'
              'folder path are replaced; it still shows your GPU, CPU and Linux setup. You can open the zip to check it first.');return
    if args.command=='build':build(c,args.portable)
    elif args.command=='install':install(c)
    elif args.command=='diagnose':diagnose(c)
    elif args.command=='smoke':launch(c,'usb',smoke=True)
    elif args.command=='launch':launch(c,args.mode)

def notify(message):
    # Menu launches have no terminal; show failures on the desktop instead.
    # Notification bodies are markup, so "&&" in a suggested command must be escaped.
    if not sys.stderr.isatty() and shutil.which('notify-send'):
        subprocess.run(['notify-send','--app-name=CrealityScan','--icon=scanner','CrealityScan could not start',
                        html.escape(message,quote=False)],check=False)

if __name__=='__main__':
    try:main()
    except (OSError,ValueError,KeyError,RuntimeError,subprocess.CalledProcessError)as e:
        print('Refused/failed:',e,file=sys.stderr);notify(str(e));sys.exit(1)
