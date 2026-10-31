"""Run the actual C RAW10 meter against synthetic padded Bayer frames."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import numpy as np

ROOT=Path(__file__).resolve().parent

class MeterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler=shutil.which('cc')
        if not compiler:raise unittest.SkipTest('C compiler unavailable')
        cls.tmp=tempfile.TemporaryDirectory();cls.program=Path(cls.tmp.name)/'meter'
        source=Path(cls.tmp.name)/'meter.c'
        source.write_text('''#include <stdio.h>
#include "metering.h"
int main(void){unsigned char b[64*96];if(fread(b,1,sizeof(b),stdin)!=sizeof(b))return 2;
struct camera_meter m=meter_raw(b,64,64,96);
printf("{\\"median\\":%.9f,\\"p98\\":%.9f,\\"saturated\\":%.9f,\\"red\\":%.9f,\\"blue\\":%.9f,\\"cells\\":%u,\\"ratio\\":%.9f}",m.median,m.p98,m.saturated,m.red,m.blue,m.cells,meter_exposure_ratio(m));return 0;}
''')
        subprocess.run([compiler,'-std=c11','-Wall','-Wextra','-Werror','-I',str(ROOT),str(source),'-lm','-o',str(cls.program)],check=True,capture_output=True)
    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()
    def meter(self,red,green,blue):
        raw=np.empty((64,64),np.uint16);raw[::2,::2]=red;raw[::2,1::2]=green;raw[1::2,::2]=green;raw[1::2,1::2]=blue
        rows=[]
        for row in raw:
            groups=row.reshape(-1,4);packed=np.empty((16,5),np.uint8)
            packed[:,:4]=groups>>2;packed[:,4]=(groups[:,0]&3)|((groups[:,1]&3)<<2)|((groups[:,2]&3)<<4)|((groups[:,3]&3)<<6)
            rows.append(packed.tobytes()+bytes([255])*16)  # padding must be ignored
        return json.loads(subprocess.check_output([str(self.program)],input=b''.join(rows)))
    def test_packing_black_subtraction_padding_and_wb(self):
        m=self.meter(164,264,114)
        self.assertEqual(m['cells'],64);self.assertAlmostEqual(m['median'],200/959,places=7)
        self.assertAlmostEqual(m['red'],2.);self.assertAlmostEqual(m['blue'],4.)
        self.assertEqual(m['saturated'],0.)
    def test_dark_frame_has_bounded_increase_and_no_invalid_wb(self):
        m=self.meter(64,64,64)
        self.assertEqual(m['ratio'],2.);self.assertEqual(m['red'],1.);self.assertEqual(m['blue'],1.)
    def test_saturated_frame_reduces_exposure_and_excludes_bad_wb(self):
        m=self.meter(1023,1023,1023)
        self.assertEqual(m['saturated'],1.);self.assertEqual(m['ratio'],.5);self.assertEqual(m['red'],1.)
    def test_midgrey_is_stable(self):
        self.assertEqual(self.meter(237,237,237)['ratio'],1.)
    def test_gain_estimates_are_bounded(self):
        m=self.meter(81,850,81)
        self.assertEqual(m['red'],4.);self.assertEqual(m['blue'],4.)

if __name__=='__main__':unittest.main()
