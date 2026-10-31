"""Approved runtime sensor mode for mission demo. No boot/kernel configuration."""
import argparse,math,os,re,subprocess,json
from pathlib import Path

def run(*args):return subprocess.run(args,check=True,capture_output=True,text=True).stdout

def configure(width=640,height=480,gain=0,fps=15,exposure=None):
    if (width,height) not in ((640,480),(1640,1232),(1920,1080)):raise ValueError('Choose tested native 640x480, 1640x1232 or 1920x1080 mode')
    if not 0<=gain<=232 or not 5<=fps<=30:raise ValueError('Gain must be 0–232 and target FPS 5–30')
    run('v4l2-ctl','-d','/dev/v4l-subdev0','--set-subdev-fmt',f'pad=0,width={width},height={height},code=0x300f')
    run('v4l2-ctl','-d','/dev/video0',f'--set-fmt-video=width={width},height={height},pixelformat=pRAA')
    actual=run('v4l2-ctl','-d','/dev/v4l-subdev0','--get-ctrl','pixel_rate,horizontal_blanking')
    values={k:int(v) for k,v in re.findall(r'(pixel_rate|horizontal_blanking):\s*(\d+)',actual)}
    line=width+values['horizontal_blanking'];total=math.ceil(values['pixel_rate']/(line*fps));vb=max(32,total-height)
    maximum=height+vb-4
    if exposure is None:exposure=min(maximum,round(.016667*values['pixel_rate']/line))
    if not 4<=exposure<=maximum:raise ValueError(f'Exposure lines must be between 4 and {maximum} at this frame rate')
    run('v4l2-ctl','-d','/dev/v4l-subdev0','--set-ctrl',f'vertical_blanking={vb},exposure={exposure},analogue_gain={gain},digital_gain=256')
    result={'mode':[width,height],'target_fps':fps,'exposure_lines':exposure,'exposure_ms':exposure*line/values['pixel_rate']*1000,
        'analogue_gain_register':gain,'analogue_gain_multiplier':256/(256-gain),'format':run('v4l2-ctl','-d','/dev/video0','--get-fmt-video')}
    runtime=Path(__file__).resolve().parents[1]/'.runtime';runtime.mkdir(exist_ok=True,mode=0o700);(runtime/'camera-settings.json').write_text(json.dumps(result,indent=2))
    return result
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--width',type=int,default=int(os.environ.get('TURTBOT_CAMERA_WIDTH',640)));p.add_argument('--height',type=int,default=int(os.environ.get('TURTBOT_CAMERA_HEIGHT',480)));p.add_argument('--gain',type=int,default=int(os.environ.get('TURTBOT_CAMERA_GAIN',0)));p.add_argument('--fps',type=int,default=int(os.environ.get('TURTBOT_CAMERA_FPS',15)));p.add_argument('--exposure',type=int);a=p.parse_args();print(json.dumps(configure(a.width,a.height,a.gain,a.fps,a.exposure),indent=2))
